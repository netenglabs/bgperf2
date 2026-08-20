#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

usage() {
  cat <<'EOF'
Usage:
  scripts/prepare_mrt.sh <local-mrt-file|routeviews-url>

Examples:
  scripts/prepare_mrt.sh mrt/rib.20260808.0000
  scripts/prepare_mrt.sh https://archive.routeviews.org/route-views2/bgpdata/2026.08/RIBS/rib.20260808.0000.bz2
EOF
}

if [[ $# -ne 1 ]]; then
  usage >&2
  exit 1
fi

SOURCE="$1"
LOCAL_PATH=""

if [[ "$SOURCE" =~ ^https?:// ]]; then
  mkdir -p mrt
  base="$(basename "$SOURCE")"
  download_path="mrt/$base"
  echo "Downloading $SOURCE"
  curl -fL "$SOURCE" -o "$download_path.part"
  mv "$download_path.part" "$download_path"
  if [[ "$download_path" == *.bz2 ]]; then
    bunzip2 -fk "$download_path"
    LOCAL_PATH="${download_path%.bz2}"
  else
    LOCAL_PATH="$download_path"
  fi
else
  LOCAL_PATH="$SOURCE"
  if [[ "$LOCAL_PATH" == *.bz2 ]]; then
    bunzip2 -fk "$LOCAL_PATH"
    LOCAL_PATH="${LOCAL_PATH%.bz2}"
  fi
fi

if [[ ! -f "$LOCAL_PATH" ]]; then
  echo "MRT file not found after preparation: $LOCAL_PATH" >&2
  exit 1
fi

ABS_LOCAL_PATH="$(readlink -f "$LOCAL_PATH")"

echo "Prepared MRT file: $LOCAL_PATH"
echo
echo "Running bgpdump2 validation:"
COUNTS_FILE="$(mktemp /tmp/prepare_mrt_counts.XXXXXX)"
trap 'rm -f "$COUNTS_FILE"' EXIT
docker run --rm --entrypoint= -v "$ABS_LOCAL_PATH:/root/mrt_file" \
  bgperf/bgpdump2 /usr/local/sbin/bgpdump2 -c /root/mrt_file | tee "$COUNTS_FILE"

echo
COUNTS_FILE="$COUNTS_FILE" python3 - <<'PY'
import os
import re

counts = []
with open(os.environ["COUNTS_FILE"], "r", encoding="utf-8") as f:
    for line in f:
        m = re.search(r"([0-9]+)[^0-9]*$", line.rstrip())
        if m:
            counts.append(int(m.group(1)))

if counts:
    print("Best-effort numeric summary:")
    print(f"  lines with trailing counts: {len(counts)}")
    print(f"  maximum trailing count: {max(counts)}")
else:
    print("Best-effort numeric summary unavailable; inspect raw bgpdump2 output above.")
PY

echo
echo "Use this exact filename in benchmark configs: $LOCAL_PATH"
