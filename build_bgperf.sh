#!/bin/bash
# Build every daemon image in parallel.
#
# `bgperf2.py prepare` does the same thing serially; this is the faster path
# when you are rebuilding everything from scratch.

set -u
cd "$(dirname "$0")" || exit 1

PYTHON=venv/bin/python
[ -x "$PYTHON" ] || PYTHON=python3

for image in exabgp exabgp_mrtparse gobgp bird frr_c rustybgp openbgp bgpdump2; do
    "$PYTHON" bgperf2.py update "$image" &
done

wait
echo "all builds finished; run '$PYTHON bgperf2.py doctor' to check"
