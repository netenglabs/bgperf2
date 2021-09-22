#!/bin/bash
# This script is used to set everything up to run tests on a new VM or installation

wget -q http://archive.routeviews.org/bgpdata/2021.08/RIBS/rib.20210801.0000.bz2 && bzip2 -d rib.20210801.0000.bz2 &
sudo apt update
sudo apt upgrade --yes
sudo apt install docker.io --yes
sudo apt install python3-pip --yes
sudo apt install sysstat --yes
sudo apt install emacs-nox --yes
sudo usermod -aG docker ubuntu

pip3 install -r pip-requirements.txt

sudo /sbin/shutdown now -r
# the user group permissions need to be applied, so easiest to log out

# python3 bgperf.py update exabgp & python3 bgperf.py update gobgp & python3 bgperf.py update bird & python3 bgperf.py update frr & python3 bgperf.py update frr_c & python3 bgperf.py update rustybgp & python3 bgperf.py update openbgp & python3 bgperf.py update bgpdump2 & 
# -- just in case ython3 bgperf.py prepare && python3 bgperf.py update frr_c && python3 bgperf.py update bgpdump2