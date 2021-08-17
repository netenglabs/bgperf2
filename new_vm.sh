#!/bin/bash
sudo apt update
sudo apt upgrade --yes
sudo apt install docker.io --yes
sudo apt install python3-pip
sudo apt install sysstat
sudo usermod -aG docker ubuntu
git clone https://github.com/jopietsch/bgperf.git
cd bgperf
pip3 install -r pip-requirements.txt
python3 bgperf.py prepare && python3 bgperf.py update frr_c && python3 bgperf.py update bgpdump2
