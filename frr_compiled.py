

from base import *
from frr import  FRRoutingTarget


class FRRoutingCompiled(Container):
    CONTAINER_NAME = None
    GUEST_DIR = '/root/config'

    def __init__(self, host_dir, conf, image='bgperf/frr_c'):
        super(FRRoutingCompiled, self).__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)

    @classmethod
    def build_image(cls, force=False, tag='bgperf/frr_c', checkout='stable/8.0', nocache=False):
        # copied from https://github.com/FRRouting/frr/blob/master/docker/ubuntu-ci/Dockerfile
        cls.dockerfile = '''
ARG UBUNTU_VERSION=22.04
FROM ubuntu:$UBUNTU_VERSION AS builder

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
        sudo \
        time \
        tshark \
        valgrind \
        yodl \
      && \
    download-mibs && \
    wget https://raw.githubusercontent.com/FRRouting/frr-mibs/main/iana/IANA-IPPM-METRICS-REGISTRY-MIB -O /usr/share/snmp/mibs/iana/IANA-IPPM-METRICS-REGISTRY-MIB && \
    wget https://raw.githubusercontent.com/FRRouting/frr-mibs/main/ietf/SNMPv2-PDU -O /usr/share/snmp/mibs/ietf/SNMPv2-PDU && \
    wget https://raw.githubusercontent.com/FRRouting/frr-mibs/main/ietf/IPATM-IPMC-MIB -O /usr/share/snmp/mibs/ietf/IPATM-IPMC-MIB && \
    python3 -m pip install wheel && \
    python3 -m pip install 'protobuf<4' grpcio grpcio-tools && \
    python3 -m pip install 'pytest>=6.2.4' 'pytest-xdist>=2.3.0' && \
    python3 -m pip install 'scapy>=2.4.5' && \
    python3 -m pip install xmltodict && \
    python3 -m pip install git+https://github.com/Exa-Networks/exabgp@0659057837cd6c6351579e9f0fa47e9fb7de7311

RUN groupadd -r -g 92 frr && \
      groupadd -r -g 85 frrvty && \
      adduser --system --ingroup frr --home /home/frr \
              --gecos "FRR suite" --shell /bin/bash frr && \
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

RUN git clone https://github.com/FRRouting/frr.git

#USER frr:frr

#COPY --chown=frr:frr . /home/frr/frr/

RUN cd frr && \
    ./bootstrap.sh && \
    ./configure \
       --prefix=/usr \
       --sysconfdir=/etc \
       --localstatedir=/var \
       --sbindir=/usr/lib/frr \
       --enable-gcov \
       --enable-dev-build \
       --enable-mgmtd-test-be-client \
       --enable-rpki \
       --enable-sharpd \
       --enable-multipath=64 \
       --enable-user=frr \
       --enable-group=frr \
       --enable-config-rollbacks \
       --enable-grpc \
       --enable-vty-group=frrvty \
       --enable-snmp=agentx \
       --enable-scripting \
       --with-pkg-extra-version=-my-manual-build && \
    make -j $(nproc) && \
    sudo make install

RUN cd frr && make check || true
RUN cp /frr/docker/ubuntu-ci/docker-start /usr/sbin/docker-start && rm -rf /frr
CMD ["/usr/sbin/docker-start"]

#RUN sudo mkdir /etc/frr && sudo chown frr:frr /etc/frr && \
#    sudo mkdir -p /root/config && sudo chown frr:frr /root/config

'''.format(checkout)
        print("FRRoutingCompiled")
        super(FRRoutingCompiled, cls).build_image(force, tag, nocache)


class FRRoutingCompiledTarget(FRRoutingCompiled, FRRoutingTarget):
    
    CONTAINER_NAME = 'bgperf_frrouting_compiled_target'

    def __init__(self, host_dir, conf, image='bgperf/frr_c'):
        super(FRRoutingTarget, self).__init__(host_dir, conf, image='bgperf/frr_c')
