

import re

from base import *
from frr import  FRRoutingTarget


class FRRoutingCompiled(Container):
    CONTAINER_NAME = None
    GUEST_DIR = '/root/config'
    IMAGE_REPO = 'bgperf/frr_c'
    # What `prepare -t frr_c` builds alongside the master build: the end of the
    # 8.x and 9.x series, and both ends of 10.x. Each one is a full FRR compile,
    # so this stays a shortlist -- add others with `update frr_c --version X.Y`.
    #
    # These are branch tips, so '8.5' is the latest 8.5.x plus any fixes merged
    # since. For an exact release use the three-part form ('8.5.7'), which
    # resolves to the frr-8.5.7 tag instead.
    VERSIONS = ('8.5', '9.1', '10.0', '10.7')
    DEFAULT_REF = 'master'

    BUILD_VARS = {
        'ubuntu_version': '22.04',
        # Runs just before ./configure, for dependencies a release needs that
        # the current recipe does not install. 'true' is the do-nothing default.
        'extra_setup': 'true',
        'configure_extra': '',
    }

    # Older releases drift away from the current recipe -- a distro that no
    # longer has their dependencies, a configure flag that did not exist yet.
    # Override per series here; first match wins, so list specific before broad:
    #
    #   VERSION_BUILD_VARS = (
    #       ('8.', {'ubuntu_version': '20.04'}),
    #       ('10', {'configure_extra': '--enable-grpc'}),
    #   )
    #
    # If a version needs a different Dockerfile rather than different values,
    # put one in dockerfiles/frr_c/<version>.dockerfile instead.
    VERSION_BUILD_VARS = ()

    def __init__(self, host_dir, conf, image='bgperf/frr_c'):
        super(FRRoutingCompiled, self).__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)

    @classmethod
    def resolve_ref(cls, version):
        '''FRR versions map onto its branch and tag naming.

        A release series lives on a maintenance branch ('10.1' -> stable/10.1),
        a bare major means its first release ('9' -> stable/9.0), and a full
        point release is a tag ('10.1.1' -> frr-10.1.1). Anything else passes
        through, so 'master' or a sha still work.
        '''
        if not version:
            return cls.DEFAULT_REF
        version = str(version).strip()
        if re.fullmatch(r'\d+', version):
            return 'stable/{0}.0'.format(version)
        if re.fullmatch(r'\d+\.\d+', version):
            return 'stable/{0}'.format(version)
        if re.fullmatch(r'\d+\.\d+\.\d+', version):
            return 'frr-{0}'.format(version)
        return version

    @classmethod
    def build_image(cls, force=False, tag=None, checkout=None, nocache=False, version=None):
        tag = tag or cls.image_tag()
        v = cls.build_vars(version)
        v['ref'] = checkout or v['ref']
        # copied from https://github.com/FRRouting/frr/blob/master/docker/ubuntu-ci/Dockerfile
        #  but you have to remove any lines that include # comments
        #
        # NOTE: this is a format string -- a literal { or } added below has to
        # be doubled, and every {name} must exist in BUILD_VARS.
        cls.dockerfile = '''
ARG UBUNTU_VERSION={ubuntu_version}
FROM ubuntu:$UBUNTU_VERSION

ARG DEBIAN_FRONTEND=noninteractive
ENV APT_KEY_DONT_WARN_ON_DANGEROUS_USAGE=DontWarn

# Update and install build requirements.

RUN apt update && apt upgrade -y && \
    apt-get install -y \
            autoconf \
            automake \
            bison \
            build-essential \
            flex \
            git \
            install-info \
            libc-ares-dev \
            libcap-dev \
            libelf-dev \
            libjson-c-dev \
            libpam0g-dev \
            libreadline-dev \
            libsnmp-dev \
            libsqlite3-dev \
            lsb-release \
            libtool \
            lcov \
            make \
            perl \
            pkg-config \
            python3-dev \
            python3-sphinx \
            screen \
            texinfo \
            tmux \
            iptables \
    && \
    apt-get install -y \
        libprotobuf-c-dev \
        protobuf-c-compiler \
    && \
    apt-get install -y \
        cmake \
        libpcre2-dev \
    && \
    apt-get install -y \
        libgrpc-dev \
        libgrpc++-dev \
        protobuf-compiler-grpc \
    && \
    apt-get install -y \
        curl \
        gdb \
        kmod \
        iproute2 \
        iputils-ping \
        liblua5.3-dev \
        libssl-dev \
        lua5.3 \
        net-tools \
        python3 \
        python3-pip \
        snmp \
        snmp-mibs-downloader \
        snmpd \
        ssmping \
        sudo \
        time \
        tshark \
        valgrind \
        yodl \
      && \
    download-mibs && \
    wget --tries=5 --waitretry=10 --retry-connrefused https://raw.githubusercontent.com/FRRouting/frr-mibs/main/iana/IANA-IPPM-METRICS-REGISTRY-MIB -O /usr/share/snmp/mibs/iana/IANA-IPPM-METRICS-REGISTRY-MIB && \
    wget --tries=5 --waitretry=10 --retry-connrefused https://raw.githubusercontent.com/FRRouting/frr-mibs/main/ietf/SNMPv2-PDU -O /usr/share/snmp/mibs/ietf/SNMPv2-PDU && \
    wget --tries=5 --waitretry=10 --retry-connrefused https://raw.githubusercontent.com/FRRouting/frr-mibs/main/ietf/IPATM-IPMC-MIB -O /usr/share/snmp/mibs/ietf/IPATM-IPMC-MIB && \
    rm -f /usr/lib/python3.*/EXTERNALLY-MANAGED && \
    python3 -m pip install wheel && \
    bash -c "PV=($(pkg-config --modversion protobuf | tr '.' ' ')); if (( PV[0] == 3 && PV[1] < 19 )); then python3 -m pip install 'protobuf<4' grpcio grpcio-tools; else python3 -m pip install 'protobuf>=4' grpcio grpcio-tools; fi" && \
    python3 -m pip install 'pytest>=6.2.4' 'pytest-xdist>=2.3.0' && \
    python3 -m pip install 'scapy>=2.4.5' && \
    python3 -m pip install xmltodict && \
    python3 -m pip install git+https://github.com/Exa-Networks/exabgp@0659057837cd6c6351579e9f0fa47e9fb7de7311


ARG UID=1010
RUN groupadd -r -g 92 frr && \
      groupadd -r -g 85 frrvty && \
      adduser --system --ingroup frr --home /home/frr \
              --gecos "FRR suite" -u $UID --shell /bin/bash frr && \
      usermod -a -G frrvty frr && \
      useradd -d /var/run/exabgp/ -s /bin/false exabgp && \
      echo 'frr ALL = NOPASSWD: ALL' | tee /etc/sudoers.d/frr && \
      mkdir -p /home/frr && chown frr.frr /home/frr

# Install FRR built packages
RUN mkdir -p /etc/apt/keyrings && \
    curl -s -o /etc/apt/keyrings/frrouting.gpg https://deb.frrouting.org/frr/keys.gpg && \
    echo deb '[signed-by=/etc/apt/keyrings/frrouting.gpg]' https://deb.frrouting.org/frr \
        $(lsb_release -s -c) "frr-stable" > /etc/apt/sources.list.d/frr.list && \
    apt-get update && apt-get install -y librtr-dev libyang2-dev libyang2-tools


#USER frr:frr
# Clone and checkout in one layer on purpose: the ref is part of the layer key,
# so a version released after an earlier build still gets a fresh clone instead
# of a cached one that has never heard of its branch.
RUN cd ~/ && git clone https://github.com/FRRouting/frr.git && cd frr && git checkout {ref}

RUN {extra_setup}



#COPY --chown=frr:frr ./ /home/frr/frr/

RUN cd ~/frr && \
    ./bootstrap.sh && \
    ./configure \
       --prefix=/usr \
       --sysconfdir=/etc \
       --localstatedir=/var/run/frr \
       --sbindir=/usr/lib/frr \
       --enable-gcov \
       --enable-rpki \
       --enable-multipath=256 \
       --enable-user=frr \
       --enable-group=frr \
       --enable-vty-group=frrvty \
       --enable-snmp=agentx \
       --enable-scripting \
       --enable-configfile-mask=0640 \
       --enable-logfile-mask=0640 \
       {configure_extra} \
       --with-pkg-extra-version=-my-manual-build && \
    make -j $(nproc) && \
    sudo make install

RUN cd ~/frr && make check || true

#RUN sudo cp ~/frr/docker/ubuntu-ci/docker-start /usr/sbin/docker-start

#CMD ["/usr/sbin/docker-start"]

RUN sudo install -m 755 -o frr -g frr -d /var/log/frr && \
    sudo install -m 755 -o frr -g frr -d /var/opt/frr && \
    sudo install -m 775 -o frr -g frrvty -d /etc/frr && \
    sudo install -m 640 -o frr -g frr /dev/null /etc/frr/zebra.conf &&  \
    sudo install -m 640 -o frr -g frr /dev/null /etc/frr/bgpd.conf && \
    sudo install -m 640 -o frr -g frrvty /dev/null /etc/frr/vtysh.conf && \
    sudo install -m 755 -o frr -g frr -d /var/lib/frr && \
    sudo install -m 755 -o frr -g frr -d /var/etc/frr && \
    sudo install -m 755 -o frr -g frr -d /var/run/frr && \
    touch /var/bgpd.pid && chown frr.frr /var/bgpd.pid


#RUN sudo mkdir /etc/frr /var/lib/frr /var/run/frr /frr
#    sudo chown frr:frr /etc/frr /var/lib/frr /var/run/frr
#    sudo mkdir -p /root/config && sudo chown frr:frr /root/config

'''.format(**v)
        print('FRRoutingCompiled: {0} from {1} (ubuntu {2})'.format(tag, v['ref'], v['ubuntu_version']))
        super(FRRoutingCompiled, cls).build_image(force, tag, nocache=nocache)


class FRRoutingCompiledTarget(FRRoutingCompiled, FRRoutingTarget):
    
    CONTAINER_NAME = 'bgperf_frrouting_compiled_target'

    def __init__(self, host_dir, conf, image='bgperf/frr_c'):
        super(FRRoutingTarget, self).__init__(host_dir, conf, image=image)
