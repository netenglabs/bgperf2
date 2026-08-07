#!/bin/bash
# This script is used to set everything up to run tests on a new VM or installation
# Run it from the repo root.

set -u

# The benchmark configs under benchmarks/ refer to mrt/rib.20210801.0000
mkdir -p mrt
if [ ! -f mrt/rib.20210801.0000 ]; then
    wget -q -O mrt/rib.20210801.0000.bz2 \
        http://archive.routeviews.org/bgpdata/2021.08/RIBS/rib.20210801.0000.bz2 \
        && bzip2 -d mrt/rib.20210801.0000.bz2 &
fi

sudo apt update
sudo apt upgrade --yes
sudo apt install docker.io --yes
sudo apt install python3-venv --yes
sudo apt install sysstat --yes
sudo usermod -aG docker "$USER"

python3 -m venv venv
venv/bin/pip install -r pip-requirements.txt

wait

echo
echo "Setup done. Reboot (or log out and back in) so the docker group applies, then:"
echo "  venv/bin/python bgperf2.py prepare   # build the daemon images"
echo "  venv/bin/python bgperf2.py doctor    # check the result"
