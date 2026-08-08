
import toml
from base import *
from gobgp import GoBGPTarget


class RustyBGP(Container):
    CONTAINER_NAME = None
    GUEST_DIR = '/root/config'
    IMAGE_REPO = 'bgperf/rustybgp'
    # RustyBGP has never cut a release: the crate has read 0.2.0 since 2020 and
    # the v0.2.0 git tag was only created in 2026. So a "version" here is a date
    # label for a git ref, and anything not in VERSION_REFS passes through as a
    # raw ref, which keeps `--version <sha>` working.
    #
    # RustyBGP ships no Cargo.lock (it is gitignored), so every build resolves
    # its dependency graph fresh. The git ref pins the source but not what it
    # compiles against, and rebuilding an old ref gets harder as the ecosystem
    # moves: 2024-12 (340f521, what benchmarks/baseline benched as
    # v0.2.0-340f521b79) no longer builds at all -- on rustc 1.87 a transitive
    # `home` needs 1.88, and on 1.97 tokio-stream fails to compile. It is
    # deliberately not listed: a recipe that cannot build is worse than none.
    DEFAULT_REF = 'master'
    VERSIONS = ('2026-02',)
    VERSION_REFS = {
        # The project was dormant from 2023-07 until 2026-01, then rewritten
        # hard (103/39/67/466 commits in Mar/Apr/May/Jun 2026). 2026-02 is the
        # last commit before that wave, so it is the "old but current-ish"
        # comparison point.
        '2026-02': '0cc685c',
    }

    BUILD_VARS = {
        # rust:1-bullseye is frozen at 1.87 (Debian 11 is EOL) and tonic 0.14
        # needs 1.88, so the modern refs build on bookworm. Pin the builder's
        # distro explicitly: bare `rust:1` is trixie (glibc 2.41) and the
        # runtime is bookworm (glibc 2.36), which builds cleanly and then dies
        # at startup with "GLIBC_2.xx not found" -- a bench that will not come
        # up rather than a build error.
        'base_image': 'rust:1-bookworm',
        'runtime_image': 'debian:bookworm',
        # api/build.rs runs protoc and prost stopped vendoring it, so the
        # builder needs it -- upstream CI installs it explicitly too.
        'packages': 'protobuf-compiler',
        # bench polls neighbour state with `gobgp neighbor -j`, so the bundled
        # CLI has to speak the same gRPC API generation the daemon serves.
        # RustyBGP moved to the GoBGP v4 API in 2026-01; master is tested
        # against v4.7.0 upstream.
        'gobgp_version': '4.7.0',
        # No-op unless a version needs its manifest patched before it builds.
        'patch': 'true',
    }
    # Matched against the version string the user typed, so each entry has to
    # accept the sha spelling as well as the label: `--version 0cc685c` names
    # the same commit as `--version 2026-02`, and matching only the label would
    # silently hand that sha the wrong recipe.
    #
    # Compared as a sha *prefix*, not for equality. The abbreviation a user
    # actually has in hand is whatever the daemon printed --
    # `rustybgpd v0.2.0-0cc685c882` -- so an exact match against the 7-char
    # spelling here would miss `0cc685c882` and quietly fall back to the
    # default recipe, bundling a v4.7 gobgp CLI with a daemon serving the v4.0
    # API: exactly the mismatch this override exists to prevent.
    VERSION_BUILD_VARS = (
        # The 2026-01 refresh landed on the v4.0 API.
        (lambda v: RustyBGP.names_commit(v, '2026-02', '0cc685c'),
         {'gobgp_version': '4.0.0'}),
    )

    @staticmethod
    def names_commit(version, label, sha):
        '''True if `version` is `label`, or any sha abbreviation of `sha`.

        Either spelling can be longer than the other -- the user may type more
        of the sha than is written here, or less -- so accept a match in both
        directions, with a floor that stops a one-character `--version 0` from
        claiming the commit.
        '''
        version = str(version).strip()
        if version == label:
            return True
        if len(version) < 6:
            return False
        return version.startswith(sha) or sha.startswith(version)

    def __init__(self, host_dir, conf, image='bgperf/rustybgp'):
        super(RustyBGP, self).__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)

    @classmethod
    def resolve_ref(cls, version):
        '''Map a date label onto its git ref; anything else is already a ref.'''
        if not version:
            return cls.DEFAULT_REF
        version = str(version).strip()
        return cls.VERSION_REFS.get(version, version)

    @classmethod
    def build_image(cls, force=False, tag=None, checkout=None, nocache=False, version=None):
        # Clone and checkout share a layer so the ref is part of the layer key:
        # a cached clone from an older build would not know a newer commit.
        tag = tag or cls.image_tag()
        v = cls.build_vars(version)
        v['ref'] = checkout or v['ref']
        cls.dockerfile = '''
FROM {base_image} AS rust_builder
RUN apt-get update && apt-get install -qy {packages}
RUN rustup component add rustfmt
RUN git clone https://github.com/osrg/rustybgp.git && cd rustybgp && git checkout {ref}
RUN cd rustybgp && {patch} && cargo build --release && cp target/release/rustybgpd /root
RUN wget https://github.com/osrg/gobgp/releases/download/v{gobgp_version}/gobgp_{gobgp_version}_linux_amd64.tar.gz
RUN tar xzf gobgp_*.tar.gz
RUN cp gobgp /root


FROM {runtime_image}
WORKDIR /root
COPY --from=rust_builder /root/rustybgpd ./
COPY --from=rust_builder /root/gobgp ./
'''.format(**v)
        super(RustyBGP, cls).build_image(force, tag, nocache=nocache)


class RustyBGPTarget(RustyBGP, GoBGPTarget):
    # RustyBGP has the same config as GoBGP
    #  except some things are different
    
    CONTAINER_NAME = 'bgperf_rustybgp_target'

    def __init__(self, host_dir, conf, image='bgperf/rustybgp'):
        super(GoBGPTarget, self).__init__(host_dir, conf, image=image)

    def write_config(self):
        # I don't want to figure out how to write config as TOML Instead of YAML, 
        #  but RustyBGP can only handle TOML, so I'm cheating
        config = super(RustyBGPTarget, self).write_config()
        del config['policy-definitions']
        del config['defined-sets']

        toml_config = toml.dumps(config)
        with open('{0}/{1}'.format(self.host_dir, self.CONFIG_FILE_NAME), 'w') as f:
            f.write(toml_config)
            if 'filter_test' in self.conf:
                f.write(self.get_filter_test_config())

    def get_filter_test_config(self):
        with open(REPO_ROOT / 'filters' / 'rustybgpd.conf') as file:
            filters = file.read()
        filters += "\n[global.apply-policy.config]\n"
        filters += f"import-policy-list = [\"{self.conf['filter_test']}\"]"
        return filters

    def get_startup_cmd(self):
        return '\n'.join(
            ['#!/bin/bash',
             'ulimit -n 65536',
             'RUST_BACKTRACE=1 /root/rustybgpd -f {guest_dir}/{config_file_name} > {guest_dir}/rustybgp.log 2>&1']
        ).format(
            guest_dir=self.guest_dir,
            config_file_name=self.CONFIG_FILE_NAME,
            debug_level='info')

    def get_version_cmd(self):
        return "/root/rustybgpd --version"
    
    def exec_version_cmd(self):
        version = self.get_version_cmd()
        i= dckr.exec_create(container=self.name, cmd=version, stderr=False)
        return dckr.exec_start(i['Id'], stream=False, detach=False).decode('utf-8').strip()
