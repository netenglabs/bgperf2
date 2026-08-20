#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

usage() {
  cat <<'EOF'
Usage:
  scripts/preflight_2026_suite.sh --config FILE [--config FILE ...] --workdir DIR --run-root DIR
EOF
}

CONFIGS=()
WORKDIR=""
RUN_ROOT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)
      CONFIGS+=("${2:?missing value for --config}")
      shift 2
      ;;
    --workdir)
      WORKDIR="${2:?missing value for --workdir}"
      shift 2
      ;;
    --run-root)
      RUN_ROOT="${2:?missing value for --run-root}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ ${#CONFIGS[@]} -eq 0 || -z "$WORKDIR" || -z "$RUN_ROOT" ]]; then
  usage >&2
  exit 1
fi

choose_python() {
  local candidate
  for candidate in "venv/bin/python" "python3"; do
    if [[ "$candidate" == "python3" ]] || [[ -x "$candidate" ]]; then
      if "$candidate" - <<'PY' >/dev/null 2>&1
import bgperf2
PY
      then
        echo "$candidate"
        return 0
      fi
    fi
  done
  echo "no usable Python with bgperf2 dependencies found; install the repo environment first" >&2
  echo "expected something like: venv/bin/pip install -r pip-requirements.txt" >&2
  exit 1
}

PYTHON_BIN="$(choose_python)"
BGPERF_CMD=("$PYTHON_BIN" "bgperf2.py")

mkdir -p "$WORKDIR" "$RUN_ROOT"

echo "Running preflight"
"${BGPERF_CMD[@]}" doctor >/dev/null

fstype_for() {
  local path="$1"
  if command -v findmnt >/dev/null 2>&1; then
    findmnt -n -o FSTYPE -T "$path" 2>/dev/null || true
  else
    df -T "$path" 2>/dev/null | awk 'NR==2 {print $2}'
  fi
}

workdir_fstype="$(fstype_for "$WORKDIR")"
if [[ "$workdir_fstype" == "tmpfs" ]]; then
  echo "WARNING: workdir is tmpfs-backed: $WORKDIR" >&2
fi

for path in "$WORKDIR" "$RUN_ROOT"; do
  if [[ ! -w "$path" ]]; then
    echo "preflight failed: not writable: $path" >&2
    exit 1
  fi
done

echo "Disk availability:"
df -h "$WORKDIR" "$RUN_ROOT"

echo "Memory availability:"
free -h

"$PYTHON_BIN" - "${CONFIGS[@]}" <<'PY'
import os
import sys
import yaml

import bgperf2


class Loader(yaml.SafeLoader):
    pass


Loader.yaml_implicit_resolvers = {
    ch: [(tag, regexp) for tag, regexp in resolvers if tag != 'tag:yaml.org,2002:float']
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def fail(msg: str) -> None:
    print(f"preflight failed: {msg}", file=sys.stderr)
    raise SystemExit(1)


all_targets = []
mrt_files = set()

for cfg in sys.argv[1:]:
    if not os.path.exists(cfg):
        fail(f"config does not exist: {cfg}")
    with open(cfg, "r", encoding="utf-8") as f:
        data = yaml.load(f, Loader=Loader)
    if not isinstance(data, dict):
        fail(f"config must contain a YAML mapping: {cfg}")
    tests = data.get("tests") or []
    if not tests:
        fail(f"config has no tests: {cfg}")
    for test in tests:
        if not isinstance(test, dict):
            fail(f"test entry must be a mapping in {cfg}")
        for target in test.get("targets", []):
            if not isinstance(target, dict) or not target.get("name"):
                fail(f"target is missing a name in {cfg}")
            all_targets.append(target)
            if "mrt_file" in target:
                mrt_files.add(target["mrt_file"])

for mrt_file in sorted(mrt_files):
    if not os.path.exists(mrt_file):
        fail(f"mrt_file does not exist: {mrt_file}")

expanded = []
for target in all_targets:
    expanded.extend(bgperf2.expand_target_versions([target]))

bgperf2.check_batch_images(expanded)

print("preflight image and mrt_file checks passed")
PY
