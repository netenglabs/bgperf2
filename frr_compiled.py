

from base import *
from frr import  FRRoutingTarget


class FRRoutingCompiled(Container):
    CONTAINER_NAME = None
    GUEST_DIR = '/root/config'

    def __init__(self, host_dir, conf, image='bgperf/frr_c'):
        super(FRRoutingCompiled, self).__init__(self.CONTAINER_NAME, image, host_dir, self.GUEST_DIR, conf)

    @classmethod
    def build_image(cls, force=False, tag='bgperf/frr_c', checkout='stable/8.0', nocache=False):
        # copied from https://github.com/FRRouting/frr/blob/master/docker/ubuntu20-ci/Dockerfile
        cls.dockerfile = '''
FROM ubuntu:20.04
WORKDIR /root
ARG DEBIAN_FRONTEND=noninteractive
ENV APT_KEY_DONT_WARN_ON_DANGEROUS_USAGE=DontWarn
# Update Ubuntu Software repository
RUN apt update && \
    apt-get install -y \
      git autoconf automake libtool make libreadline-dev texinfo \
      pkg-config libpam0g-dev libjson-c-dev bison flex python3-pytest \
      libc-ares-dev python3-dev python-ipaddress python3-sphinx \
      install-info build-essential libsnmp-dev perl \
      libcap-dev python2 libelf-dev \
      sudo gdb curl iputils-ping time \
      libgrpc++-dev libgrpc-dev protobuf-compiler-grpc \
      lua5.3 liblua5.3-dev \
      mininet iproute2 iperf && \
      curl https://bootstrap.pypa.io/pip/2.7/get-pip.py --output /tmp/get-pip.py && \
      python2 /tmp/get-pip.py && \
      rm -f  /tmp/get-pip.py && \
      pip2 install ipaddr && \
      pip2 install "pytest<5" && \
      pip2 install "scapy>=2.4.2" && \
      pip2 install exabgp==3.4.17

RUN groupadd -r -g 92 frr && \
      groupadd -r -g 85 frrvty && \
      adduser --system --ingroup frr --home /home/frr \
              --gecos "FRR suite" --shell /bin/bash frr && \
      usermod -a -G frrvty frr && \
      useradd -d /var/run/exabgp/ -s /bin/false exabgp && \
      echo 'frr ALL = NOPASSWD: ALL' | tee /etc/sudoers.d/frr && \
      mkdir -p /home/frr && chown frr.frr /home/frr

#for libyang 2
RUN apt-get install -y cmake libpcre2-dev

#USER frr:frr

# build and install libyang2
RUN cd && pwd && ls -al && \
    git clone https://github.com/CESNET/libyang.git && \
    cd libyang && \
    git checkout v2.0.0 && \
    mkdir build; cd build && \
    cmake -DCMAKE_INSTALL_PREFIX:PATH=/usr \
          -DCMAKE_BUILD_TYPE:String="Release" .. && \
    make -j $(nproc) && \
    sudo make install

RUN cd && git clone https://github.com/FRRouting/frr.git -b frr-8.0 frr

RUN cd && ls -al && ls -al frr

RUN ls ~/frr/

RUN cd ~/frr && \
    ./bootstrap.sh && \
    ./configure \
       --prefix=/usr \
       --localstatedir=/var/run/frr \
       --sbindir=/usr/lib/frr \
       --sysconfdir=/etc/frr \
       --enable-vtysh \
       --enable-grpc \
       --enable-pimd \
       --enable-sharpd \
       --enable-multipath=64 \
       --enable-user=frr \
       --enable-group=frr \
       --enable-vty-group=frrvty \
       --enable-snmp=agentx \
       --enable-scripting \
       --with-pkg-extra-version=-bgperf && \
    make -j $(nproc) && \
    sudo make install

#RUN sudo mkdir /etc/frr && sudo chown frr:frr /etc/frr && \
#    sudo mkdir -p /root/config && sudo chown frr:frr /root/config

'''.format(checkout)
        print("FRRoutingCompiled")
        super(FRRoutingCompiled, cls).build_image(force, tag, nocache)


class FRRoutingCompiledTarget(FRRoutingCompiled, FRRoutingTarget):
    
    CONTAINER_NAME = 'bgperf_frrouting_compiled_target'

    def __init__(self, host_dir, conf, image='bgperf/frr_c'):
        super(FRRoutingTarget, self).__init__(host_dir, conf, image='bgperf/frr_c')
