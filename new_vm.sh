#!/bin/bash
#git clone https://github.com/jopietsch/bgperf.git
sudo apt update
sudo apt upgrade --yes
sudo apt install docker.io --yes
sudo apt install python3-pip --yes
sudo apt install sysstat --yes
sudo apt install emacs-nox --yes
sudo usermod -aG docker ubuntu

cd bgperf
pip3 install -r pip-requirements.txt
python3 bgperf.py prepare && python3 bgperf.py update frr_c && python3 bgperf.py update bgpdump2
