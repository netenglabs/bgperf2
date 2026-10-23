#!/bin/bash
# This script is used to set everything up to run tests on a new VM or installation
# Run it from the repo root.

set -eu

# Install the supported interpreter separately if the distro does not provide it.
command -v python3.14 >/dev/null || { echo "Python 3.14 is required" >&2; exit 1; }

sudo apt update
sudo apt upgrade --yes
sudo apt install docker.io --yes
sudo apt install python3.14-venv --yes
sudo apt install sysstat --yes
sudo usermod -aG docker "$USER"

python3.14 "$(dirname "$0")/scripts/bootstrap.py"

echo
echo "Setup done. Reboot (or log out and back in) so the docker group applies, then:"
echo "  venv/bin/python bgperf2.py prepare   # build the daemon images"
echo "  venv/bin/python bgperf2.py doctor    # check the result"
