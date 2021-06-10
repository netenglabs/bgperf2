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

from base import *

class ExaBGP(Container):

    GUEST_DIR = '/root/config'

    def __init__(self, name, host_dir, conf, image='bgperf/exabgp'):
        super(ExaBGP, self).__init__('bgperf_exabgp_' + name, image, host_dir, self.GUEST_DIR, conf)


    # This Dockerfile has parts borrowed from exabgps Dockerfile
    @classmethod
    def build_image(cls, force=False, tag='bgperf/exabgp', checkout='HEAD', nocache=False):
        cls.dockerfile = '''
FROM python:3-buster


ENV PYTHONPATH "/tmp/exabgp/src"

RUN apt update \
    && apt -y dist-upgrade \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/*

ADD . /tmp/exabgp
WORKDIR /tmp/exabgp
RUN ln -s src/exabgp exabgp

RUN echo Building exabgp 
RUN pip3 install --upgrade pip setuptools wheel
RUN pip3 install exabgp
WORKDIR /root

RUN ln -s /root/exabgp /exabgp
#ENTRYPOINT ["/bin/bash"]
'''.format(checkout)
        super(ExaBGP, cls).build_image(force, tag, nocache)


class ExaBGP_MRTParse(Container):

    GUEST_DIR = '/root/config'

    def __init__(self, name, host_dir, conf, image='bgperf/exabgp_mrtparse'):
        super(ExaBGP_MRTParse, self).__init__('bgperf_exabgp_mrtparse_' + name, image, host_dir, self.GUEST_DIR, conf)

    @classmethod
    def build_image(cls, force=False, tag='bgperf/exabgp_mrtparse', checkout='HEAD', nocache=False):
        cls.dockerfile = '''
FROM python:3-slim-buster

ENV PYTHONPATH "/tmp/exabgp/src"

RUN apt update \
    && apt -y dist-upgrade \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/*

ADD . /tmp/exabgp
WORKDIR /tmp/exabgp
RUN ln -s src/exabgp exabgp

RUN echo Building exabgp 
RUN pip3 install --upgrade pip setuptools wheel
RUN pip3 install exabgp
WORKDIR /root

RUN ln -s /root/exabgp /exabgp
ENTRYPOINT ["/bin/bash"]
'''.format(checkout)
        super(ExaBGP_MRTParse, cls).build_image(force, tag, nocache)
