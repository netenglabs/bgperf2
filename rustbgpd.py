'''rustbgpd: an API-first BGP daemon written in Rust.

The image is built from a release tag rather than a moving branch: rustbgpd
tags a release roughly weekly, so 'whatever master was that day' would make
two runs a week apart incomparable with nothing in the results to say why.
Anything not matching a release number still passes through as a raw ref, so
`--version <branch|sha>` keeps working.
'''
import json

from base import *


class RustBGPd(Container):
    CONTAINER_NAME = None
    GUEST_DIR = '/root/config'
    IMAGE_REPO = 'bgperf/rustbgpd'
    DAEMON_BINARY = '/usr/local/bin/rustbgpd'
    DEFAULT_REF = 'v0.66.0'

    BUILD_VARS = {
        # Pinned to the workspace's declared rust-version (1.95 at v0.66.0)
        # rather than a floating 'rust:1': the daemon states an MSRV, and a
        # toolchain older than it does not compile at all. Bookworm matches the
        # runtime below -- a builder on a newer distro links against a newer
        # glibc and produces a binary that builds cleanly and then dies at
        # startup with "GLIBC_2.xx not found".
        'base_image': 'rust:1.95-bookworm',
        'runtime_image': 'debian:bookworm-slim',
        # crates/api generates its gRPC stubs with prost, which stopped
        # vendoring protoc, so the builder needs it from the distro.
        'packages': 'protobuf-compiler',
    }

    def __init__(self, host_dir, conf, image='bgperf/rustbgpd'):
        super(RustBGPd, self).__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)

    @classmethod
    def resolve_ref(cls, version):
        '''rustbgpd tags releases as v<version>; branches and shas pass through.'''
        if not version:
            return cls.DEFAULT_REF
        version = str(version).strip()
        if re.fullmatch(r'\d+(\.\d+)*', version):
            return 'v{0}'.format(version)
        return version

    @classmethod
    def build_image(cls, force=False, tag=None, checkout=None, nocache=False, version=None):
        # Clone and checkout share a layer so the ref is part of the layer key:
        # a cached clone from an older build would not know a newer tag.
        tag = tag or cls.image_tag()
        v = cls.build_vars(version)
        v['ref'] = checkout or v['ref']
        cls.dockerfile = '''
FROM {base_image} AS builder
RUN apt-get update && apt-get install -qy {packages}
WORKDIR /build
RUN git clone https://github.com/lance0/rustbgpd.git . && git checkout {ref}
# --locked: the repository commits Cargo.lock, so the build resolves the
# dependency graph the tag was tested against instead of whatever the registry
# offers today. Only the two binaries the bench runs are built; the workspace
# also carries libraries, examples and tools that nothing here starts.
RUN cargo build --release --locked -p rustbgpd -p rustbgpctl

FROM {runtime_image}
WORKDIR /root
# iproute2: base.Container.run() reads `ip addr` in the container to find the
# interface carrying the benchmark address.
RUN apt-get update && apt-get install -qy iproute2 && rm -rf /var/lib/apt/lists/*
COPY --from=builder /build/target/release/rustbgpd /usr/local/bin/rustbgpd
COPY --from=builder /build/target/release/rbgp /usr/local/bin/rbgp
# The daemon's default runtime state directory, where it puts the gRPC socket
# that rbgp connects to.
RUN mkdir -p /var/lib/rustbgpd
'''.format(**v)
        super(RustBGPd, cls).build_image(force, tag, nocache=nocache)

    def get_version_cmd(self):
        return 'rustbgpd --version'

    def exec_version_cmd(self):
        # `rustbgpd --version` prints 'rustbgpd <semver>' on stdout and nothing
        # else. Anything else is the container answering instead of the daemon
        # -- an exec error, a missing binary -- and recording that as a version
        # makes a results row quietly unreproducible.
        ret = (super(RustBGPd, self).exec_version_cmd() or '').strip()
        if not ret.startswith('rustbgpd '):
            raise VersionUnavailable(
                'unexpected output from `{0}`: {1!r}'.format(self.get_version_cmd(), ret))
        return ret


class RustBGPdTarget(RustBGPd, Target):

    CONTAINER_NAME = 'bgperf_rustbgpd_target'
    CONFIG_FILE_NAME = 'config.toml'

    def write_config(self):
        self.reject_unsupported_policy()

        config = '[global]\n'
        config += 'asn = {}\n'.format(self.conf['as'])
        config += 'router_id = "{}"\n'.format(self.conf['router-id'])
        config += 'listen_port = 179\n'
        config += '\n'
        config += '[global.telemetry]\n'
        config += 'prometheus_addr = "0.0.0.0:9179"\n'
        config += 'log_format = "json"\n'
        config += '\n'
        # No gRPC security block: since v0.63.0 the daemon grants local-operator
        # authorization implicitly on its owner-only default unix socket, which
        # is all `rbgp` needs from inside the container. (The older
        # `[security.grpc] enforcement = "legacy"` escape hatch was removed in
        # that same release -- a config carrying it is rejected at startup.)
        #
        # The durable event-history outbox shipped default-on in v0.31.0 and
        # became opt-in (`enabled = false`) in v0.32.0. This target builds any
        # ref, so a v0.31.0-or-earlier build would run with event history on
        # and a later one with it off, and the outbox moves both memory use and
        # convergence. RUSTBGPD_EVENT_HISTORY_OFF writes the setting out
        # explicitly, normalizing it across the whole version range the target
        # can build.
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

    def reject_unsupported_policy(self):
        '''Refuse a run whose policy inputs this target would silently drop.

        write_config() emits plain [[neighbors]] blocks and no policy at all,
        so a filter run against this target would produce an unfiltered
        measurement filed under a filter label -- the one result a reader
        cannot spot afterwards. Raise instead, before any container starts.
        '''
        unsupported = []
        if self.conf.get('filter_test'):
            unsupported.append('target.filter_test')
        if self.scenario_global_conf.get('policy'):
            unsupported.append('policy')
        for tester in self.scenario_global_conf.get('testers') or []:
            for name, n in (tester or {}).get('neighbors', {}).items():
                if any((n.get('filter') or {}).values()):
                    unsupported.append('testers.neighbors.{0}.filter'.format(name))
        if unsupported:
            raise NotImplementedError(
                'the rustbgpd target does not generate policy configuration, so it '
                'would ignore: {0}'.format(', '.join(sorted(set(unsupported)))))

    def get_startup_cmd(self):
        return '\n'.join(
            ['#!/bin/bash',
             'ulimit -n 65536',
             'exec rustbgpd {guest_dir}/{config_file_name} > {guest_dir}/rustbgpd.log 2>&1']
        ).format(
            guest_dir=self.guest_dir,
            config_file_name=self.CONFIG_FILE_NAME)

    def get_neighbors_state(self):
        '''Parse `rbgp --json neighbor`, which lists every configured peer.

        rustbgpd reports one received-prefix count per neighbor and does not
        separate received from accepted, so both dicts carry the same number.
        '''
        neighbors_received = {}
        neighbors_accepted = {}
        output = self.local('rbgp --json neighbor')
        if not output:
            # Normal for the first poll or two: the daemon has not opened its
            # socket yet, so rbgp exits with a message and no JSON.
            return neighbors_received, neighbors_accepted
        try:
            neighbors = json.loads(output.decode('utf-8'))
        except ValueError:
            return neighbors_received, neighbors_accepted
        for n in neighbors:
            received = n.get('prefixes_received', 0)
            neighbors_received[n.get('address', '')] = received
            neighbors_accepted[n.get('address', '')] = received
        return neighbors_received, neighbors_accepted
