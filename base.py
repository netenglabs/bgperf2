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

from settings import dckr
import glob
import hashlib
import io
import json
import os
import re
from docker.utils import version_gte
from itertools import chain
from pathlib import Path
from threading import Thread
import netaddr
import sys
import time
import datetime
from jinja2 import Environment, FileSystemLoader, PackageLoader, StrictUndefined, make_logging_undefined

from measurements import offering_poll_can_stop


# Resource files (filters/, nos_templates/) live next to the source,
# so anchor them to the source directory rather than the working directory.
# Without this, bgperf2 can only be run from the repo root.
REPO_ROOT = Path(__file__).resolve().parent

flatten = lambda l: chain.from_iterable(l)

def get_ctn_names():
    names = list(flatten(n['Names'] for n in dckr.containers(all=True)))
    return [n[1:] if n[0] == '/' else n for n in names]


def ctn_exists(name):
    return name in get_ctn_names()


def normalize_image_name(name):
    '''Add the implicit ':latest' to a bare repository name.

    A tag only counts as a tag if it comes after the last '/' -- otherwise the
    port in a registry host ('localhost:5000/bgperf/bird') reads as one.
    '''
    return name if ':' in name.rsplit('/', 1)[-1] else name + ':latest'


def _find_image(name, images=None):
    '''The local image dict carrying exactly this repository:tag, or None.

    The one scan img_exists() and img_recipe_label() both need -- kept in one
    place so a future fix to the matching itself (this already replaced one
    bug, comparing only RepoTags[0]) cannot be made in one and not the other.

    `images` takes a pre-fetched dckr.images() listing, for a caller (doctor,
    images) about to ask this question many times in one command -- each
    dckr.images() call is a full local-image listing, and asking it once per
    daemon per version otherwise turns one health check into dozens of Docker
    API round trips. Fetched fresh here when omitted, as every caller before
    this parameter existed already got.
    '''
    name = normalize_image_name(name)
    for img in (dckr.images() if images is None else images):
        if name in (img.get('RepoTags') or []):
            return img
    return None


def img_exists(name, images=None):
    '''True if a local image carries exactly this repository:tag.

    This used to compare only the repository half of RepoTags[0], so
    'bgperf/frr_c:10.1' looked present the moment any bgperf/frr_c image
    existed -- which is why version tags were impossible and the old FRR
    builds had to fake them with path-like names ('bgperf/frr_c/stable_8').
    Reading every RepoTag also fixes images that carry more than one tag.
    '''
    return _find_image(name, images) is not None


# `prepare`/`build_dockerfile()` skip a tag that already exists, so a recipe
# changed after that point -- a new apt package, a fixed ENTRYPOINT, a
# resolve_ref() that now maps a version to a different checkout -- is
# invisible until someone thinks to force a rebuild. That has happened three
# times over (FRR's gcov flags, exabgp/bgpdump2's base image and autoreconf)
# and each was closed by a hand-written, date-stamped paragraph telling the
# operator to rebuild -- exactly the kind of prose this label replaces with
# something checkable.
#
# It is not a substitute for PULL_BASE: OpenBGPD's `FROM openbgpd/openbgpd:
# latest` is the same text before and after upstream republishes new content
# under that tag, so the rendered recipe -- and this hash -- do not change
# when only the *content behind a moving tag* drifts. That is what pulls_base()
# forces a fresh `pull` for; this label answers a different question, whether
# the recipe bgperf2 owns has moved on since the image was built.
RECIPE_LABEL_KEY = 'bgperf2.recipe_hash'


def recipe_hash(dockerfile_text, buildargs=None):
    '''A short content hash of a rendered Dockerfile plus its buildargs.

    Hashed rather than written into the image as a `LABEL` line in the
    Dockerfile text itself, so the hash plays no part in what it is a hash
    of -- passed to `docker build` as an image label instead, which is read
    back by img_recipe_label().

    `buildargs` matters for an override Dockerfile (dockerfile_override()):
    its text is the same for every version routed through it, and only
    BGPERF_REF/BGPERF_VERSION -- passed as buildargs, not baked into the
    file -- vary per version. Hashing the text alone would be blind to a
    resolve_ref() change for any such version, exactly the "recipe changed"
    case this mechanism exists to catch.
    '''
    # A structured encoding of the pair, not a bare concatenation -- text
    # plus buildargs with no delimiter between them could in principle be
    # split two different ways to the same string.
    fingerprint = json.dumps([dockerfile_text, buildargs or {}], sort_keys=True)
    return hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()[:12]


def img_recipe_label(name, images=None):
    '''The recipe hash a local image was built with, or None.

    None covers two cases that must read the same way to a caller: the tag
    does not exist, or it was built before this label existed. Either way
    there is nothing to compare against, which is the same shape as
    bgpdump2's "commit unknown" for a pruned clone -- said explicitly rather
    than guessed. See _find_image() for `images`.
    '''
    img = _find_image(name, images)
    return (img.get('Labels') or {}).get(RECIPE_LABEL_KEY) if img else None


def sanitize_tag(version):
    '''Turn a version string into something Docker will accept as a tag.

    Docker tags are [A-Za-z0-9_.-] only, so refs like 'stable/10.1' have to be
    flattened. The tag is display-only -- resolve_ref() is what the build
    actually checks out.
    '''
    tag = re.sub(r'[^A-Za-z0-9_.-]', '_', str(version).strip())
    return tag.lstrip('.-')[:128] or 'latest'


# Sentinel for an optional parameter whose real values include None --
# render_dockerfile()'s `_override` is None both when unset and when a
# version genuinely has no override file, and those must not be confused.
_UNSET = object()


class _RenderOnly:
    '''Flag that makes build_dockerfile assemble the recipe but not run it.

    Set only by Container.render_dockerfile, which needs the text a build
    would use without spending a build to get it.
    '''
    active = False


class VersionNotSupported(Exception):
    '''A version was asked for from a daemon that only has the one build.'''


# Marker written into results when a daemon's version could not be read. It is
# deliberately loud: a blank or guessed version silently makes a run
# irreproducible, which is only discovered when someone tries to repeat it.
VERSION_UNKNOWN = 'UNKNOWN'


class VersionUnavailable(Exception):
    '''A daemon's version command ran but did not report a usable version.'''


class ImageBuildFailed(Exception):
    '''Docker reported an error while building an image.'''
    def __init__(self, tag, message):
        self.tag = tag
        self.message = message
        super(ImageBuildFailed, self).__init__(
            'building {0} failed: {1}'.format(tag, message))


class ImageNotBuilt(Exception):
    '''A run asked for a version whose image does not exist locally.

    Carries the command that would produce it, because guessing the tag by
    hand is exactly the step this whole mechanism exists to remove.
    '''
    def __init__(self, image_name, version, tag, buildable=True):
        self.image_name = image_name
        self.version = version
        self.tag = tag
        if buildable:
            fix = './bgperf2.py update {0}{1}'.format(
                image_name, ' --version {0}'.format(version) if version else '')
        else:
            fix = ('download the image out of band and tag it: '
                   'docker tag <downloaded-image> {0}'.format(tag))
        super(ImageNotBuilt, self).__init__(
            "docker image '{0}' does not exist. To create it, {1}".format(tag, fix))


def rm_line():
    print('\x1b[1A\x1b[2K\x1b[1D\x1b[1A')


class Container(object):
    # --- image naming and daemon versions ---------------------------------
    #
    # Every image bgperf2 knows about is <IMAGE_REPO>:<tag>, where the tag comes
    # from a user-facing version string ('10.1', '9.0', '2.15.1'). resolve_ref()
    # translates that version into the git ref (or upstream image tag) the build
    # actually uses -- that is where each daemon's release-naming quirks live,
    # so nothing outside the daemon module has to know that FRR 10.1 means
    # 'stable/10.1' while BIRD 2.15.1 means 'v2.15.1'.
    #
    #   IMAGE_REPO        repository half of the image name
    #   VERSIONS          versions `prepare` builds in addition to the default
    #   DEFAULT_REF       ref used when no version is given (the ':latest' tag)
    #   SUPPORTS_VERSIONS False for daemons pinned to one build (Flock)
    #   IMAGE_BUILDABLE   False for images downloaded out of band (crpd, cEOS)
    #   PULL_BASE         re-pull the FROM image on every build
    IMAGE_REPO = None
    VERSIONS = ()
    DEFAULT_REF = 'HEAD'
    SUPPORTS_VERSIONS = True
    IMAGE_BUILDABLE = True
    # Off by default: most daemons are compiled from a git ref here, so the
    # base image is only a toolchain and a stale local copy costs nothing that
    # matters. Set it where the base image IS the daemon under test -- there,
    # a cached `FROM upstream:latest` means the tag quietly stops tracking
    # upstream, and the run records a version nobody asked for.
    #
    # It applies to the unversioned tag only (see pulls_base()). A version tag
    # builds `FROM upstream:9.2`, which is immutable, so re-pulling it cannot
    # find anything new -- and `pull` is fatal when the registry is unreachable
    # even though the image is already local, which would turn an offline
    # `prepare -t openbgp` into a failure it never used to be.
    PULL_BASE = False

    # --- image verification -----------------------------------------------
    #
    # `bgperf2 verify` starts a throwaway container per built image and asks
    # the daemon about itself. It covers the seam the test suite cannot: a
    # parser meeting a real container. Both bugs that reached master this way
    # -- rustybgp reading its version with GoBGP's parser, openbgpd's bgpctl
    # under a path that does not exist -- look fine in isolation and only fail
    # against the image.
    #
    #   DAEMON_BINARY        the binary under test, for build-hygiene checks
    #   VERSION_NEEDS_DAEMON version command talks to a running daemon, so it
    #                        cannot be probed from a bare container
    DAEMON_BINARY = None
    VERSION_NEEDS_DAEMON = False

    @classmethod
    def pulls_base(cls, tag):
        '''Whether this build should re-pull its FROM image.'''
        if not cls.PULL_BASE or cls.IMAGE_REPO is None:
            return False
        # Normalize first: image_tag() returns 'bgperf/openbgp:latest', but the
        # bare repo name is what every daemon's __init__ defaults to, so a
        # caller passing 'bgperf/openbgp' would otherwise silently skip the
        # re-pull with nothing to show it had been skipped.
        return normalize_image_name(tag) == cls.image_tag()

    # --- version-dependent build recipes ----------------------------------
    #
    # Old releases rarely build with the current recipe: the base distro moves
    # on, dependency packages get renamed, configure flags appear and vanish.
    # Two levels of override, cheapest first:
    #
    # BUILD_VARS holds the slots the inline Dockerfile interpolates by name
    # ({base_image}, {configure_extra}, ...). VERSION_BUILD_VARS overrides
    # some of them for a version series -- a list of (match, overrides) pairs
    # where match is a version prefix ('8.', '10') or a callable taking the
    # version string. The first match wins, so put the specific ones first.
    #
    # When a version needs a genuinely different Dockerfile rather than
    # different values, drop one in dockerfiles/<name>/<version>.dockerfile;
    # it is used verbatim and wins over the inline recipe. Longest version
    # prefix wins ('10.1.1' tries 10.1.1, then 10.1, then 10), so one file can
    # cover a whole series. Those files get BGPERF_REF and BGPERF_VERSION as
    # docker build args -- declare `ARG BGPERF_REF` after FROM to use them.
    BUILD_VARS = {}
    VERSION_BUILD_VARS = ()

    @classmethod
    def image_name(cls):
        '''The name this daemon goes by on the command line and in batch yaml.'''
        return (cls.IMAGE_REPO or '').split('/')[-1]

    @classmethod
    def build_vars(cls, version=None):
        '''Dockerfile slots for this version: defaults plus the first match.'''
        out = dict(cls.BUILD_VARS)
        version = '' if version is None else str(version).strip()
        for match, overrides in cls.VERSION_BUILD_VARS:
            hit = match(version) if callable(match) else version.startswith(match)
            if hit:
                out.update(overrides)
                break
        out.setdefault('version', version)
        out.setdefault('ref', cls.resolve_ref(version or None))
        return out

    @classmethod
    def dockerfile_override(cls, version=None):
        '''A hand-written Dockerfile for this version, if the repo has one.'''
        if not version:
            return None
        name = cls.image_name()
        parts = str(version).strip().split('.')
        for i in range(len(parts), 0, -1):
            path = REPO_ROOT / 'dockerfiles' / name / ('.'.join(parts[:i]) + '.dockerfile')
            if path.exists():
                return path
        return None

    @classmethod
    def resolve_ref(cls, version):
        '''Map a user-facing version onto the ref the Dockerfile checks out.

        The default is a passthrough, so an unrecognized value is always usable
        as a raw ref (a branch, tag, or sha) without special-casing.
        '''
        if not version:
            return cls.DEFAULT_REF
        return version

    @classmethod
    def image_tag(cls, version=None):
        if cls.IMAGE_REPO is None:
            raise NotImplementedError(
                '{0} has no IMAGE_REPO, so it cannot be addressed by version'.format(cls.__name__))
        if not version:
            return normalize_image_name(cls.IMAGE_REPO)
        if not cls.SUPPORTS_VERSIONS:
            raise VersionNotSupported(
                '{0} is built from a fixed upstream release; it has no selectable '
                'versions (asked for {1!r})'.format(cls.image_name(), version))
        return '{0}:{1}'.format(cls.IMAGE_REPO, sanitize_tag(version))

    @classmethod
    def build_version(cls, version=None, force=False, nocache=False):
        '''Build one version of this daemon into its own tag.'''
        tag = cls.image_tag(version)
        ref = cls.resolve_ref(version)
        override = cls.dockerfile_override(version)
        # Announce the build here rather than inside build_image(), which
        # render_dockerfile() also calls -- a print there ends up inside the
        # rendered recipe.
        print('{0}: {1} from {2}{3}'.format(
            cls.image_name(), tag, ref,
            ' using {0}'.format(override.relative_to(REPO_ROOT)) if override is not None else ''))
        if override is not None:
            cls.build_dockerfile(override.read_text(), force, tag, nocache=nocache,
                                 buildargs=cls.override_buildargs(version))
        else:
            cls.build_image(force=force, tag=tag, checkout=ref, nocache=nocache, version=version)
        return tag

    @classmethod
    def override_buildargs(cls, version):
        '''The buildargs an override Dockerfile is built with for this version.

        Shared by build_version() (which builds it) and current_recipe_hash()
        (which has to fingerprint the identical shape) so the two cannot
        drift apart from each other.
        '''
        return {'BGPERF_REF': cls.resolve_ref(version), 'BGPERF_VERSION': str(version)}

    @classmethod
    def require_image(cls, version=None):
        '''Return the image for this version, or explain how to build it.

        bench() calls this before touching Docker so a long batch fails in the
        first second rather than an hour in, and with the fix in the message.
        '''
        tag = cls.image_tag(version)
        if not img_exists(tag):
            raise ImageNotBuilt(cls.image_name(), version, tag, cls.IMAGE_BUILDABLE)
        return tag

    @classmethod
    def built_versions(cls, images=None):
        '''Version tags of this daemon that exist locally, for `doctor`.

        See _find_image() for `images`.
        '''
        if cls.IMAGE_REPO is None:
            return []
        prefix = cls.IMAGE_REPO + ':'
        tags = set()
        for img in (dckr.images() if images is None else images):
            for repo_tag in img.get('RepoTags') or []:
                if repo_tag.startswith(prefix):
                    tags.add(repo_tag[len(prefix):])
        return sorted(tags)

    def __init__(self, name, image, host_dir, guest_dir, conf):
        self.name = name
        self.image = image
        self.host_dir = host_dir
        self.guest_dir = guest_dir
        self.conf = conf
        self.config_name = None
        self.stop_monitoring = False
        # Interface carrying this container's benchmark addresses; filled in by
        # run() once Docker has attached the networks.
        self.dev = 'eth0'
        self.command = None
        self.environment = None
        self.volumes = [self.guest_dir]
        if not os.path.exists(host_dir):
            os.makedirs(host_dir)
            os.chmod(host_dir, 0o777)
        print(f"image: {image}")

    @classmethod
    def build_image(cls, force, tag, nocache=False, checkout=None, version=None, buildargs=None):
        '''Build cls.dockerfile, which the daemon module has just assembled.

        checkout/version are accepted and ignored so a daemon that does not
        override this still works with build_version() -- forwarding them to
        build_dockerfile() raised TypeError instead, which is a trap for exactly
        the case CLAUDE.md tells you to write.
        '''
        cls.build_dockerfile(cls.dockerfile, force, tag, nocache=nocache, buildargs=buildargs)

    @classmethod
    def render_dockerfile(cls, version=None, _override=_UNSET):
        '''The Dockerfile a version would build, without building it.

        Debugging a failed build by running it is a compile-length round trip
        per attempt, so let the recipe be read directly instead.

        `_override` lets a caller that has already resolved
        dockerfile_override() (current_recipe_hash(), which also needs it to
        decide the buildargs) pass it straight in rather than probing the
        filesystem for the same version a second time; every other caller
        leaves it unset and this resolves it itself as before. A sentinel,
        not None -- a version with no override resolves to None too, and
        that is a real answer this must not re-probe for.
        '''
        override = cls.dockerfile_override(version) if _override is _UNSET else _override
        if override is not None:
            return override.read_text()
        _RenderOnly.active = True
        try:
            cls.build_image(force=False, tag=cls.image_tag(version),
                            checkout=cls.resolve_ref(version), version=version)
        finally:
            _RenderOnly.active = False
        return cls.dockerfile

    @classmethod
    def current_recipe_hash(cls, version=None):
        '''The hash a build of this version would carry right now.

        Mirrors build_version() via override_buildargs(): an override
        Dockerfile is built with BGPERF_REF/BGPERF_VERSION as buildargs,
        which have to be part of the fingerprint the same way
        build_dockerfile() folds them in at build time, or a resolve_ref()
        change for a version routed through an override would leave this
        hash unchanged.
        '''
        override = cls.dockerfile_override(version)
        buildargs = cls.override_buildargs(version) if override is not None else None
        return recipe_hash(cls.render_dockerfile(version, _override=override), buildargs)

    @classmethod
    def recipe_status(cls, version=None, images=None):
        '''('ok' | 'stale' | 'unknown', current_hash) for a built tag.

        Only meaningful once the tag is known to exist -- an unbuilt tag has
        no label to compare and callers check built_versions()/img_exists()
        first. 'unknown' is what an image built before this label existed
        reports, on purpose: that is not the same claim as 'ok', and treating
        it as one would call an unrebuildable image current. See
        _find_image() for `images`.
        '''
        current = cls.current_recipe_hash(version)
        stored = img_recipe_label(cls.image_tag(version), images)
        if stored is None:
            return 'unknown', current
        return ('ok' if stored == current else 'stale'), current

    @classmethod
    def build_dockerfile(cls, dockerfile, force, tag, nocache=False, buildargs=None):
        '''Hand one Dockerfile to Docker.

        Separate from build_image so a version can supply its own Dockerfile
        (see dockerfile_override) without going through the daemon module's
        inline recipe -- the two paths differ only in where the text came from.
        '''
        cls.dockerfile = dockerfile
        if _RenderOnly.active:
            return
        def insert_after_from(dockerfile, line):
            lines = dockerfile.split('\n')
            i = -1
            for idx, l in enumerate(lines):
                elems = [e.strip() for e in l.split()]
                if len(elems) > 0 and elems[0] == 'FROM':
                    i = idx
            if i < 0:
                raise Exception('no FROM statement')
            lines.insert(i+1, line)
            return '\n'.join(lines)

        for env in ['http_proxy', 'https_proxy']:
            if env in os.environ:
                dockerfile = insert_after_from(dockerfile, 'ENV {0} {1}'.format(env, os.environ[env]))

        f = io.BytesIO(dockerfile.encode('utf-8'))
        if force or not img_exists(tag):
            print('build {0}...'.format(tag))
            # Hashed before the proxy ENV line above was spliced in, so an
            # operator's http_proxy/https_proxy cannot change the hash and
            # manufacture staleness that has nothing to do with the recipe.
            # buildargs is folded in too -- current_recipe_hash() mirrors
            # this exactly so an override Dockerfile's BGPERF_REF is
            # covered. Computed only here, not above: `prepare` re-asks this
            # for every already-built tag it plans to skip, and hashing a
            # multi-hundred-line rendered Dockerfile just to throw the
            # result away is pure waste on that path.
            label_hash = recipe_hash(cls.dockerfile, buildargs)
            build_kwargs = dict(fileobj=f, rm=False, tag=tag, decode=True, nocache=nocache,
                                pull=cls.pulls_base(tag), buildargs=buildargs or {})
            # docker-py raises InvalidVersion for `labels` below API 1.23
            # (~Engine 1.11), older than the 1.9.0 doctor()'s own version
            # check still accepts -- the label is an enhancement, not
            # something a build on an old daemon should fail over.
            if version_gte(dckr.api_version, '1.23'):
                build_kwargs['labels'] = {RECIPE_LABEL_KEY: label_hash}
            error = None
            for line in dckr.build(**build_kwargs):
                if 'stream' in line:
                    print(line['stream'].strip())

                if 'errorDetail' in line:
                    print(line['errorDetail'])
                    error = line['errorDetail']
            # Docker reports build failures in the stream rather than by raising,
            # so without this a compile error just scrolls past: `prepare` exits
            # 0, the image is missing or stale, and the mystery surfaces later as
            # a bench that will not come up.
            if error is not None:
                raise ImageBuildFailed(tag, error.get('message') or error)

    def get_ipv4_addresses(self):
        if 'local-address' in self.conf:
            local_addr = self.conf['local-address']
            return [local_addr]
        raise NotImplementedError()

    def get_host_config(self):
        host_config = dckr.create_host_config(
            binds=['{0}:{1}'.format(os.path.abspath(self.host_dir), self.guest_dir)],
            privileged=True,
            network_mode='bridge',
            cap_add=['NET_ADMIN']
        )
        return host_config

    def run(self, dckr_net_name='', rm=True):

        if rm and ctn_exists(self.name):
            print('remove container:', self.name)
            dckr.remove_container(self.name, force=True)

        host_config = self.get_host_config()

        ctn = dckr.create_container(image=self.image, command=self.command, environment=self.environment,
                                    detach=True, name=self.name,
                                    stdin_open=True, volumes=self.volumes, host_config=host_config)
        self.ctn_id = ctn['Id']

        ipv4_addresses = self.get_ipv4_addresses()

        net_id = None
        for network in dckr.networks(names=[dckr_net_name]):
            if network['Name'] != dckr_net_name:
                continue

            net_id = network['Id']
            if not 'IPAM' in network:
                print(('can\'t verify if container\'s IP addresses '
                      'are valid for Docker network {}: missing IPAM'.format(dckr_net_name)))
                break
            ipam = network['IPAM']

            if not 'Config' in ipam:
                print(('can\'t verify if container\'s IP addresses '
                      'are valid for Docker network {}: missing IPAM.Config'.format(dckr_net_name)))
                break

            ip_ok = False
            network_subnets = [item['Subnet'] for item in ipam['Config'] if 'Subnet' in item]
            for ip in ipv4_addresses:
                for subnet in network_subnets:
                    ip_ok = netaddr.IPAddress(ip) in netaddr.IPNetwork(subnet)

                if not ip_ok:
                    print(('the container\'s IP address {} is not valid for Docker network {} '
                          'since it\'s not part of any of its subnets ({})'.format(
                              ip, dckr_net_name, ', '.join(network_subnets))))
                    print(('Please consider removing the Docket network {net} '
                          'to allow bgperf to create it again using the '
                          'expected subnet:\n'
                          '  docker network rm {net}'.format(net=dckr_net_name)))
                    sys.exit(1)
            break

        if net_id is None:
            print('Docker network "{}" not found!'.format(dckr_net_name))
            return

        dckr.connect_container_to_network(self.ctn_id, net_id, ipv4_address=ipv4_addresses[0])
        dckr.start(container=self.name)

        # Containers end up on two networks: the default bridge that Docker
        # attaches at creation, plus the benchmark network connected above.
        # Which one lands on eth0 is not deterministic, so find the interface
        # actually carrying our address rather than assuming a name. Config
        # generation needs this too -- see self.dev.
        dev = None
        pxlen = None
        res = self.local('ip addr').decode("utf-8")

        for line in res.split('\n'):
            if ipv4_addresses[0] in line:
                dev = line.split(' ')[-1].strip()
                pxlen = line.split('/')[1].split(' ')[0].strip()
        if not dev:
            dev = "eth0"
            pxlen = 8

        self.dev = dev

        for ip in ipv4_addresses[1:]:
            self.local(f'ip addr add {ip}/{pxlen} dev {dev}')

        return ctn

    def stats(self, queue):
        def stats():
            if self.stop_monitoring:
                return

            for stat in dckr.stats(self.ctn_id, decode=True):
                if self.stop_monitoring:
                    return

                cpu_percentage = 0.0
                prev_cpu = stat['precpu_stats']['cpu_usage']['total_usage']
                if 'system_cpu_usage' in stat['precpu_stats']:
                    prev_system = stat['precpu_stats']['system_cpu_usage']
                else:
                    prev_system = 0
                cpu = stat['cpu_stats']['cpu_usage']['total_usage']
                system = stat['cpu_stats']['system_cpu_usage'] if 'system_cpu_usage' in stat['cpu_stats'] else 0

                cpu_num = stat['cpu_stats']['online_cpus']
                cpu_delta = float(cpu) - float(prev_cpu)
                system_delta = float(system) - float(prev_system)
                if system_delta > 0.0 and cpu_delta > 0.0:
                    cpu_percentage = (cpu_delta / system_delta) * float(cpu_num) * 100.0
                mem_usage = stat['memory_stats'].get('usage', 0)
                queue.put({'who': self.name, 'cpu': cpu_percentage, 'mem': mem_usage, 'time': datetime.datetime.now()})

        t = Thread(target=stats)
        t.daemon = True
        t.start()

    # How many consecutive failed reads before the sampler says so a second
    # time. The first is always reported; after that a target that is simply
    # unreachable would otherwise write a line a second for the rest of the run.
    NEIGHBOR_SAMPLE_REPORT_EVERY = 60

    # Class attributes so they exist on every Container however it was built --
    # `+=` rebinds onto the instance, so nothing is shared. A run reads these to
    # say whether the neighbour evidence it converged on was complete.
    neighbor_sample_failures = 0
    neighbor_sample_consecutive_failures = 0
    neighbor_sample_last_error = None

    def neighbor_stats(self, queue):
        def stats():
            while True:
                if self.stop_monitoring:
                    return
                try:
                    # Stamped before the read, on the rule both poll loops
                    # already follow: a sample dated to when its read finished
                    # is dated late by the cost of a docker exec, and this one
                    # is compared against a monitor sample stamped the same way.
                    sampled_s = time.monotonic()
                    neighbors_received_full, neighbors_checked, witness = \
                        self.sample_target_state()
                    # The witness rides on the neighbours message rather than
                    # travelling as one of its own: bench()'s dispatch reads any
                    # message from this producer carrying neither neighbour key
                    # as a cpu/mem sample, so a third shape would be read as one.
                    queue.put({'who': self.name,
                               'neighbors_checked': neighbors_checked,
                               'table_witness': witness,
                               'monotonic_s': sampled_s})
                    queue.put({'who': self.name,
                               'neighbors_received_full': neighbors_received_full})
                    self.neighbor_sample_consecutive_failures = 0
                except Exception as exc:
                    # This loop used to have no guard at all, and one bad read
                    # ended the thread for the rest of the run -- silently.
                    # What that costs is not a missing sample: it is the whole
                    # convergence verdict. `neighbors_checked` freezes at its
                    # last value, `note_neighbors_checkpoint()` never fires, and
                    # `ConvergenceTracker`'s CONVERGED gate requires that
                    # checkpoint -- so the run has no terminating path except
                    # STUCK_SAMPLES and is published FAILED with a complete,
                    # stable table in hand. Measured: the 2026-timing-validation
                    # campaign's `rustybgp default` cell at 50 x 100,000 burned
                    # 2194s that way while the target held all 5,000,000 routes
                    # and the monitor had every one of them.
                    #
                    # So the thread survives the read, and -- the other half of
                    # the same lesson -- it is never quiet about it. A sampler
                    # that fails every time still produces no checkpoint, and
                    # the only thing that distinguishes that run from a slow
                    # daemon is this saying so.
                    self.neighbor_sample_failures += 1
                    self.neighbor_sample_consecutive_failures += 1
                    self.neighbor_sample_last_error = '{0}: {1}'.format(
                        type(exc).__name__, exc)
                    if (self.neighbor_sample_consecutive_failures == 1
                            or self.neighbor_sample_consecutive_failures
                            % self.NEIGHBOR_SAMPLE_REPORT_EVERY == 0):
                        print('WARNING: {0}: neighbour sample failed '
                              '({1} consecutive, {2} total): {3}'.format(
                                  self.name,
                                  self.neighbor_sample_consecutive_failures,
                                  self.neighbor_sample_failures,
                                  self.neighbor_sample_last_error),
                              file=sys.stderr, flush=True)
                time.sleep(1)

        t = Thread(target=stats)
        t.daemon = True
        t.start()

    def local(self, cmd, stream=False, detach=False, stderr=False):
        i = dckr.exec_create(container=self.name, cmd=cmd, stderr=stderr)
        return dckr.exec_start(i['Id'], stream=stream, detach=detach)

    def get_startup_cmd(self):
        raise NotImplementedError()

    def get_version_cmd(self):
        raise NotImplementedError()

    def exec_version_cmd(self, stderr=False):
        '''Run this daemon's version command and return its raw output.

        `stderr` is load-bearing for some daemons rather than a nicety: both
        `bird --version` and `bgpctl -V` print their banner on stderr and
        nothing at all on stdout, so collecting only stdout returns an empty
        string and the version reads as unavailable.
        '''
        version = self.get_version_cmd()
        i = dckr.exec_create(container=self.name, cmd=version, stderr=stderr)
        return dckr.exec_start(i['Id'], stream=False, detach=False).decode('utf-8')

    def version_string(self):
        '''This daemon's version, or an explicit UNKNOWN saying why not.

        Results are only reproducible if a reader can tell which build produced
        them, so this never guesses: a daemon whose version command is missing
        or unparseable records the reason instead of a plausible-looking value.
        A wrong version in a results file cannot be spotted afterwards -- an
        earlier run recorded the word 'exec' as a BIRD version and it survived
        into the published baseline.
        '''
        # Every path assigns `reported` and falls through to the single
        # sanitizing return below. Returning early from a failure branch is
        # what makes this dangerous: the failure text is the *only* part of
        # this that is arbitrary -- a docker socket hiccup stringifies as
        # "('Connection aborted.', RemoteDisconnected('Remote end closed ...'))",
        # commas and all -- so the branch most in need of sanitizing was the
        # one that used to skip it.
        try:
            reported = self.exec_version_cmd()
        except NotImplementedError:
            reported = '{0} (no version command for {1})'.format(
                VERSION_UNKNOWN, type(self).__name__)
        except Exception as e:
            reported = '{0} ({1})'.format(VERSION_UNKNOWN, e)
        reported = (reported or '').strip()
        if not reported:
            reported = '{0} (no output from version command)'.format(VERSION_UNKNOWN)
        # Results are joined with ',' into CSV rows with no quoting, so a comma
        # anywhere in a version silently shifts every column after it, and a
        # newline splits one row across two lines.
        return re.sub(r'\s+', ' ', reported.replace(',', ';')).strip()

    def exec_startup_cmd(self, stream=False, detach=False):
        startup_content = self.get_startup_cmd()

        if not startup_content:
            return
        filename = '{0}/start.sh'.format(self.host_dir)
        with open(filename, 'w') as f:
            f.write(startup_content)
        os.chmod(filename, 0o777)

        return self.local('{0}/start.sh'.format(self.guest_dir),
                          detach=detach,
                          stream=stream)

    def get_test_counts(self):
        '''gets the configured counts that each tester is supposed to send'''
        tester_count = {}
        neighbors_checked = {}
        for tester in self.scenario_global_conf['testers']:
            for n in tester['neighbors'].keys():
                tester_count[n] = tester['neighbors'][n]['check-points']
                neighbors_checked[n] = False
        return tester_count, neighbors_checked

    # Whether this daemon can be asked for a gauge of the table it holds. Read
    # so that a target that *can* answer and did not -- a poll thread that died
    # on its first read, a run that converged before the first target poll --
    # is reported by name instead of producing an artifact byte-identical to a
    # daemon that was never able to answer. Same rule as the export section's
    # `unmeasured_reason`: absent is what an older build wrote, so silence
    # cannot be told from a build that took no such measurement.
    REPORTS_TABLE_WITNESS = False

    def get_table_witness(self):
        '''The target's own account of the table it holds, or None.

        None means the daemon has no gauge this project knows how to read, and
        that absence is recorded rather than filled in with a zero: a target
        that could not be asked and a target holding nothing must not produce
        the same document.

        Two daemons answer, and they answer with different halves. BIRD
        publishes all three sums. FRR publishes `exported_to_monitor` and
        `imported_paths` and withholds `best_paths` deliberately -- see
        `frr.table_witness()` -- so it cross-checks the two ends of the
        monitor's session and bounds the table's size without attesting to
        anything the convergence rule reads, which is `best_paths` alone. A
        daemon that answers partially is not a daemon that answers wrongly;
        each key stands or falls on its own.
        '''
        return None

    def sample_target_state(self):
        '''One sample of everything the target can be asked about itself.

        One call rather than two so a daemon that can answer both from a single
        CLI read -- BIRD does -- is not made to exec twice a second into the
        container it is measuring, and so the two halves describe one instant.
        '''
        neighbors_received_full, neighbors_checked = \
            self.get_neighbor_received_routes()
        return neighbors_received_full, neighbors_checked, self.get_table_witness()

    def get_neighbor_received_routes(self):
        ## if we ccall this before the daemon starts we will not get output
        neighbors_received, neighbors_accepted = self.get_neighbors_state()
        return self.classify_neighbor_counts(neighbors_received,
                                             neighbors_accepted)

    def classify_neighbor_counts(self, neighbors_received, neighbors_accepted):
        '''Turn per-neighbour counts into the two all-sent verdicts.

        Split from the CLI read so a daemon that reads its counters and its
        table gauge out of one command can reuse it.
        '''
        tester_count, neighbors_checked = self.get_test_counts()
        neighbors_received_full = neighbors_checked.copy()
        for n in neighbors_accepted.keys():

            #this will include the monitor, we don't want to check that
            if n in tester_count and neighbors_accepted[n] >= tester_count[n]: 
                neighbors_checked[n] = True

        
        for n in neighbors_received.keys():

            #this will include the monitor, we don't want to check that
            if (n in tester_count and neighbors_received[n] >= tester_count[n]) or neighbors_received[n] == True: 
                neighbors_received_full[n] = True

        return neighbors_received_full, neighbors_checked 

class Target(Container):

    CONFIG_FILE_NAME = None

    # Set by a target that can be told to re-evaluate its import policy
    # against the table it already holds, without resetting its sessions.
    # Only BIRD can so far: the mechanism is that daemon's own reconfigure
    # command over the config file bgperf2 wrote, so there is nothing generic
    # to fall back on -- which is why a policy reload is refused for every
    # other target at every entry point rather than discovered here, once the
    # run has already converged.
    SUPPORTS_POLICY_RELOAD = False

    # What the reload is carried out with, and whether it holds the BGP
    # sessions up. Both are recorded in the artifact rather than assumed: a
    # reload that resets its sessions measures a second table delivery and
    # belongs in a different comparison from one that does not, and a reader
    # cannot tell which they have without being told.
    POLICY_RELOAD_MECHANISM = None
    POLICY_RELOAD_SESSION_PRESERVING = None

    def policy_reload(self, reject_peer_asns):
        """Install an import policy rejecting these peers and apply it.

        Returns the daemon's own reply where it did not report the change
        carried out, and None where it did. A reload nobody performed has no
        symptom except the monitor's count not moving, which arrives as a stall
        minutes later and reads as a stuck target -- the same reason
        `Tester.churn()` reports its failures rather than raising.
        """
        raise NotImplementedError()

    def scenario_neighbors(self, sort=True):
        """Every BGP session this target is configured with.

        Three kinds, and this is the one place that knows there are three: the
        generators' peers, the monitor, and the export-fan-out receivers. Eight
        target modules built this list independently before receivers existed,
        each of them `flatten(testers) + [monitor]`, and a receiver added to
        seven of them is a target that quietly exports to fewer sessions than
        the run says it does -- with nothing in the row, the artifact or the
        graph to show for it.

        Receivers are deliberately *not* in `conf['testers']`. That is what
        keeps them from being route sources: `get_test_counts()` reads the
        testers, so a receiver is never waited on for a full table it will
        never send, and the monitor's check-point and the ingress accounting
        are untouched by how many of them there are.

        `sort=False` for the two callers that never sorted -- ordering is
        cosmetic in a config file, and changing it would put an unrelated diff
        in front of anyone comparing a generated config against an older run's.
        """
        conf = self.scenario_global_conf
        neighbors = list(flatten(list(t.get('neighbors', {}).values())
                                 for t in conf['testers']))
        neighbors.append(conf['monitor'])
        neighbors.extend(conf.get('receivers') or [])
        if not sort:
            return neighbors
        return sorted(neighbors, key=lambda n: n['as'])

    def monitor_neighbor_address(self):
        '''The address this target peers with the monitor on, or None.

        The monitor's `local-address` is, from the target's side, the monitor's
        neighbour address. Scenario addresses carry a prefix length and BIRD
        prints the bare address, so it is stripped here rather than at each
        reader.
        '''
        monitor = (self.scenario_global_conf or {}).get('monitor') or {}
        address = monitor.get('local-address')
        return address.split('/')[0] if address else None

    def write_config(self):
        raise NotImplementedError()

    def use_existing_config(self):
        if 'config_path' in self.conf:
            with open('{0}/{1}'.format(self.host_dir, self.CONFIG_FILE_NAME), 'w') as f:
                with open(self.conf['config_path'], 'r') as orig:
                    f.write(orig.read())
            return True
        return False

    def run(self, scenario_global_conf, dckr_net_name=''):
        self.scenario_global_conf = scenario_global_conf
        # create config before container is created
        if not self.use_existing_config():
            self.write_config()

        ctn = super(Target, self).run(dckr_net_name)


        self.exec_startup_cmd(detach=True)

        return ctn
    
    def get_template(self, data, template_file="junos.j2",):
        env = Environment(loader=FileSystemLoader(searchpath=str(REPO_ROOT / 'nos_templates')))
        template = env.get_template(template_file)
        output = template.render(data=data)
        return output

class Tester(Container):

    CONTAINER_NAME_PREFIX = None
    # Set by a generator that can be asked what it has put on the wire.
    # bench() polls only those; a generator that cannot answer records its
    # injection interval as unavailable rather than having one inferred from
    # the monitor, which would measure the target and call it the tester.
    REPORTS_OFFERING = False

    # Set by a generator that can be told to withdraw and re-announce a bounded
    # block of what it offers, which is what a churn burst is. Only the
    # synthetic BIRD generator can: it is configured from prefixes bgperf2
    # generated, so a block of them can be put in a protocol of its own and
    # switched off. An MRT injector plays a file back once and has no such
    # handle, which is why churn is refused for one at every entry point rather
    # than discovered here.
    SUPPORTS_CHURN = False

    def churn(self, action):
        '''Withdraw or re-announce this generator's churn block.

        Returns the sessions whose reply did not say the command was carried
        out, so a burst that was never issued fails the sequence immediately
        instead of being found as a stall five minutes later.
        '''
        raise NotImplementedError()

    def __init__(self, name, host_dir, conf, image):
        Container.__init__(self, self.CONTAINER_NAME_PREFIX + name, image, host_dir, self.GUEST_DIR, conf)

    def get_ipv4_addresses(self):
        res = []
        peers = list(self.conf.get('neighbors', {}).values())
        for p in peers:
            res.append(p['local-address'])
        return res

    def configure_neighbors(self, target_conf):
        raise NotImplementedError()

    def get_offerings(self):
        '''One measurements.TesterOffering per configured peer, keyed by
        session name.

        Every configured peer must appear in every poll, with offered=None
        where the read failed: TesterEventRecorder rejects a poll whose session
        keys differ from the first one, because a peer that quietly dropped out
        would let the peers that remain satisfy 'the whole table was offered'.
        '''
        raise NotImplementedError()

    def offering_stats(self, queue, stop, interval=1):
        '''Poll this generator's own counters into the run's stats queue.

        `stop` is the controller's stop Event rather than a sleep, for the
        reason the other samplers use it: batch() runs every cell in this
        process, so a poll loop that outlives its run keeps exec'ing into
        containers for every later cell and becomes contention the benchmark
        then reports as someone else's.

        The loop also ends itself once the generator has reported the whole
        workload offered -- see measurements.offering_poll_can_stop() for what
        that requires and why nothing observable is lost by stopping there.
        '''
        def poll():
            while not stop.is_set() and not self.stop_monitoring:
                # Stamped before the read, not after. One poll is a single exec
                # running a `birdc` per peer, which at 50-100 peers takes long
                # enough to matter: timestamping on return would date every
                # counter to when the read *finished* and silently inflate
                # tester_startup_s by up to a whole read, while each event still
                # claims the nominal cadence. Before the read is a lower bound
                # on when the counters were true, which is the honest end of the
                # interval to report.
                sampled_at = time.monotonic()
                try:
                    sessions = self.get_offerings()
                except Exception as e:
                    # A poll that could not be read is missing evidence, not a
                    # reason to end a run that is otherwise producing a result --
                    # but it has to be *said*. Swallowing it silently leaves an
                    # artifact whose null injection interval cannot be told
                    # apart from a generator that was read fine and never
                    # finished, which is the one ambiguity this section exists
                    # to remove.
                    queue.put({'who': self.name,
                               'tester_offering_error': repr(e),
                               'monotonic_s': sampled_at,
                               'time': datetime.datetime.now()})
                    sessions = None
                if sessions:
                    queue.put({'who': self.name,
                               'tester_offering': sessions,
                               'monotonic_s': sampled_at,
                               'time': datetime.datetime.now()})
                    # A generator that has finished has nothing further to
                    # say, and asking it anyway is the instrument charging the
                    # run for its own overhead: one poll of a BIRD tester is a
                    # `docker exec` running a `birdc` per configured peer, so a
                    # 50-100 peer run keeps spawning that many short-lived
                    # processes a second until the monitor converges. `birdc`
                    # is in contention.BGPERF_PROCESSES, which means it is the
                    # one load `max foreign cpu %` deliberately cannot see.
                    #
                    # The sample above is queued first: the poll that ends the
                    # loop is the poll that carries the completion evidence.
                    if offering_poll_can_stop(sessions):
                        return
                # Wait to a deadline measured from the sample, not a fixed
                # interval piled on top of the read. The read is the expensive
                # half -- one exec running a birdc per peer -- so sleeping a
                # whole `interval` after it makes the achieved cadence
                # `read + interval` while every event still claims the nominal
                # one, and that claim is exactly what qualifies an injection of
                # 0.0s as unresolved rather than instant.
                #
                # A read that overruns the interval keeps the full sleep
                # instead of polling back-to-back: chasing the deadline there
                # would put the controller in a container continuously, which
                # is the contention the run would then report as someone
                # else's. It is recorded rather than hidden -- the recorder
                # derives each event's resolution from the sample timestamps,
                # so a cadence this loop could not keep is published as the
                # cadence it did keep.
                remaining = sampled_at + interval - time.monotonic()
                if stop.wait(remaining if remaining > 0 else interval):
                    return

        t = Thread(target=poll)
        t.daemon = True
        t.start()

    def run(self, target_conf, dckr_net_name):
        self.ctn = super(Tester, self).run(dckr_net_name)

        self.configure_neighbors(target_conf)

    def launch(self):
        output = self.exec_startup_cmd(stream=True, detach=False)

        cnt = 0
        prev_pid = 0
        for lines in output: # This is the ExaBGP output
            lines = lines.decode("utf-8").strip().split('\n')
            for line in lines:
                fields = line.split('|')
                if len(fields) >2:
                    # Get PID from ExaBGP output
                    try:
                        # ExaBGP Version >= 4
                        # e.g. 00:00:00 | 111 | control | command/comment
                        pid = int(fields[1])
                    except ValueError:
                        # ExaBGP Version = 3
                        # e.g. 00:00:00 | INFO | 111 | control | command
                        pid = int(fields[2])
                    if pid != prev_pid:
                        prev_pid = pid
                        cnt += 1
                        if cnt > 1:
                            rm_line()
                        print('tester booting.. ({0}/{1})'.format(cnt, len(list(self.conf.get('neighbors', {}).values()))))
                else:
                    print(lines)

        return None

    @staticmethod
    def find_errors(log_dirs=(), samples=None):
        return 0

    @staticmethod
    def find_timeouts(log_dirs=(), samples=None):
        return 0


# What a captured sample costs, and why all three numbers are small.
#
# The capture runs after `bench_stop` and after the events artifact is on disk,
# so it is billed to neither `total time` nor the atomic write -- but it still
# runs in the controller process, whose own RSS feeds the recorded
# `min free mem` column. A tester log reaches hundreds of MB on an MRT run and
# a pathological line (a BGP attribute dump) is unbounded, so a capture that
# kept every match could hold more than the run it is describing. Twenty lines
# of at most 300 characters is 6 KB, and errors and timeouts are separate walks
# with separate lists, so a run carrying both holds at most 12 KB -- which
# cannot move that column either way, and is enough to say what a count of one
# or two was. A truncated capture says so rather than looking complete --
# `sampled` against `count` is the difference, and the limit is published
# beside them (as `sample_limit_per_list`, because that is what it bounds) so a
# reader need not know this constant.
#
# ERROR_SAMPLE_PER_LOG is the second bound and it exists because the first one
# alone is spent in `glob` order. A generator writes one log per session -- a
# BIRD tester one per peer, an MRT fleet one `bgpdump2.log` per injector -- so
# a global cap can be exhausted by the first session walked while the other
# forty-nine contribute nothing and the capture still looks complete. Three per
# log spreads the budget across at least seven sessions before the global cap
# binds, which is what makes a capture evidence about the *fleet* rather than
# about whichever file `glob` happened to return first.
ERROR_SAMPLE_LIMIT = 20
ERROR_SAMPLE_PER_LOG = 3
ERROR_SAMPLE_LINE_CHARS = 300


def note_error_sample(samples, log_dir, log, lineno, line, taken=0):
    '''Record one matched line, bounded, if the caller asked for samples.

    `samples is None` is the default everywhere and captures nothing, so a
    caller that only wants the count -- which is every caller that existed
    before this -- walks the logs exactly as it did.

    The line is trimmed rather than dropped when it is long: what makes a
    `tester_health` rejection diagnosable is the shape of the message, and the
    first 300 characters carry it.

    `taken` is how many this log has already contributed, and the caller keeps
    it. Returns whether the line was recorded, which is what lets the caller
    keep that count without this function rescanning `samples` -- it used to,
    once per matched line, and a log whose needle is the bare substring
    `error` can match millions of times. That scan sat between `bench_stop()`
    and `collect_provenance()`, which still has to reach containers that are
    about to go away, and in a batch it delays the next cell.

    **Both the tester and the log file are recorded, and the basename alone is
    not enough.** Every MRT injector writes the same `bgpdump2.log` inside its
    own host directory, so ten injectors produce ten samples reading
    `bgpdump2.log:1234` with nothing saying which container each came from --
    and the host directory that would have said is deleted at the start of the
    next cell, which is the whole reason this record exists. `source` is the
    tester's own directory name, which is what distinguishes them.
    '''
    if samples is None or taken >= ERROR_SAMPLE_PER_LOG:
        return False
    if len(samples) >= ERROR_SAMPLE_LIMIT:
        return False
    source = os.path.basename(os.path.normpath(log_dir))
    name = os.path.basename(log)
    text = line.rstrip('\n')
    truncated = len(text) > ERROR_SAMPLE_LINE_CHARS
    if truncated:
        text = text[:ERROR_SAMPLE_LINE_CHARS]
    samples.append({
        'source': source,
        'log': name,
        'line': lineno,
        'text': text,
        'truncated': truncated,
    })
    return True


def count_matching_lines(log_dirs, needle, samples=None):
    '''Count lines containing `needle` (case-insensitively) in each *.log
    directly inside each of `log_dirs` -- not recursively, which is all the
    testers need since they write their logs straight into guest_dir.

    The MRT testers used to shell out to `grep ... /tmp/bgperf2/...  | wc -l`,
    which hardcoded the bench directory and returned a *string*, so the stats
    row got '0\\n' where every other tester wrote an int. Reading the
    directories bench() actually passes keeps -b/--bench-name working.

    An unreadable log is skipped rather than raised: this runs at the moment a
    run has just converged but not yet written its stats row, so letting an
    OSError out would throw away the whole run over a log file. The grep this
    replaced also returned 0 in that case.
    '''
    needle = needle.lower()
    count = 0
    for log_dir in log_dirs:
        # Sorted so that which sessions a bounded capture drew from is a
        # property of the run rather than of the filesystem's `glob` order.
        for log in sorted(glob.glob(os.path.join(log_dir, '*.log'))):
            taken = 0
            try:
                with open(log, errors='replace') as f:
                    for lineno, line in enumerate(f, 1):
                        if needle in line.lower():
                            count += 1
                            if note_error_sample(samples, log_dir, log, lineno,
                                                 line, taken):
                                taken += 1
            except OSError:
                continue
    return count
