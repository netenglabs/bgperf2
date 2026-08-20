#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

usage() {
  cat <<'EOF'
Usage:
  scripts/run_2026_suite.sh <next|all|smoke|core-synth|core-mrt|filters> [options]

Options:
  --run-id ID           Stable run ID for results/2026/<run-id>
  --results-root DIR    Root for run directories (default: results/2026)
  --workdir DIR         Benchmark work directory (default: /var/tmp/bgperf)
  --mrt-file PATH       Override every mrt_file: entry in selected suites
  --force               Re-run suites even if COMPLETE marker exists
  -h, --help            Show this help
EOF
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

SUITE_SELECTOR="$1"
shift

RUN_ID=""
RESULTS_ROOT="results/2026"
WORKDIR="/var/tmp/bgperf"
MRT_FILE=""
FORCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-id)
      RUN_ID="${2:?missing value for --run-id}"
      shift 2
      ;;
    --results-root)
      RESULTS_ROOT="${2:?missing value for --results-root}"
      shift 2
      ;;
    --workdir)
      WORKDIR="${2:?missing value for --workdir}"
      shift 2
      ;;
    --mrt-file)
      MRT_FILE="${2:?missing value for --mrt-file}"
      shift 2
      ;;
    --force)
      FORCE=1
      shift
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

suite_config() {
  case "$1" in
    smoke) echo "benchmarks/2026-smoke.yaml" ;;
    core-synth) echo "benchmarks/2026-core-synth.yaml" ;;
    core-mrt) echo "benchmarks/2026-core-mrt.yaml" ;;
    filters) echo "benchmarks/2026-filters.yaml" ;;
    *)
      echo "unknown suite: $1" >&2
      exit 1
      ;;
  esac
}

if [[ "$SUITE_SELECTOR" == "all" ]]; then
  SUITES=(smoke core-synth core-mrt filters)
elif [[ "$SUITE_SELECTOR" == "next" ]]; then
  SUITES=()
else
  SUITES=("$SUITE_SELECTOR")
fi

if [[ -z "$RUN_ID" ]]; then
  RUN_ID="$(date +%Y%m%d-%H%M%S)"
fi

if [[ ! "$RUN_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "invalid run ID: use only letters, numbers, dots, underscores, and hyphens" >&2
  exit 1
fi

RUN_ROOT="${RESULTS_ROOT%/}/$RUN_ID"
METADATA_DIR="$RUN_ROOT/metadata"
CONFIG_SNAPSHOT_DIR="$METADATA_DIR/configs"
ORIGINAL_CONFIG_DIR="$CONFIG_SNAPSHOT_DIR/original"
RENDERED_CONFIG_DIR="$CONFIG_SNAPSHOT_DIR/rendered"
LOG_DIR="$METADATA_DIR/logs"

if [[ "$SUITE_SELECTOR" == "next" ]]; then
  for candidate in smoke core-synth core-mrt filters; do
    if [[ ! -f "$RUN_ROOT/$candidate/COMPLETE" ]]; then
      SUITES=("$candidate")
      break
    fi
  done
  if [[ ${#SUITES[@]} -eq 0 ]]; then
    echo "Campaign is complete: $RUN_ROOT"
    exit 0
  fi
  echo "Next incomplete suite: ${SUITES[0]}"
fi

mkdir -p "$RUN_ROOT" "$METADATA_DIR" "$ORIGINAL_CONFIG_DIR" "$RENDERED_CONFIG_DIR" "$LOG_DIR" "$WORKDIR"

echo "Run ID: $RUN_ID"
echo "Run root: $RUN_ROOT"
echo "Workdir: $WORKDIR"
if [[ -n "$MRT_FILE" ]]; then
  echo "MRT override: $MRT_FILE"
fi

render_config() {
  local suite="$1"
  local src="$2"
  local dst="$3"

  local original="$ORIGINAL_CONFIG_DIR/$suite.yaml"
  local rendered_tmp
  rendered_tmp="$(mktemp "$RENDERED_CONFIG_DIR/$suite.yaml.XXXXXX")"

  if [[ -f "$original" ]] && ! cmp -s "$src" "$original"; then
    echo "run ID $RUN_ID already has a different original config for $suite" >&2
    echo "use a new run ID instead of mixing benchmark inputs" >&2
    rm -f "$rendered_tmp"
    exit 1
  fi
  cp "$src" "$original"
  if [[ -z "$MRT_FILE" ]]; then
    cp "$src" "$rendered_tmp"
  else
    MRT_OVERRIDE="$MRT_FILE" "$PYTHON_BIN" - "$src" "$rendered_tmp" <<'PY'
import os
import re
import sys
src, dst = sys.argv[1:3]
override = os.environ["MRT_OVERRIDE"]
with open(src, "r", encoding="utf-8") as f:
    text = f.read()
text = re.sub(
    r"^(\s*mrt_file:\s*).*$",
    lambda match: match.group(1) + override,
    text,
    flags=re.MULTILINE,
)
with open(dst, "w", encoding="utf-8") as f:
    f.write(text)
PY
  fi

  if [[ -f "$dst" ]] && ! cmp -s "$rendered_tmp" "$dst"; then
    echo "run ID $RUN_ID already has a different rendered config for $suite" >&2
    echo "use a new run ID instead of changing the MRT override" >&2
    rm -f "$rendered_tmp"
    exit 1
  fi
  mv "$rendered_tmp" "$dst"
}

CAPTURED_DOCTOR=0
CAPTURED_IMAGES=0

capture_metadata() {
  local suite_list
  suite_list="$(printf '%s\n' "${SUITES[@]}")"
  local config_list
  config_list="$(printf '%s\n' "${rendered_configs[@]}")"

  git -C . rev-parse HEAD > "$METADATA_DIR/git-rev-parse-head.txt"
  git -C . status --short > "$METADATA_DIR/git-status-short.txt"
  uname -a > "$METADATA_DIR/uname-a.txt"
  free -h > "$METADATA_DIR/free-h.txt"
  {
    df -h "$WORKDIR"
    df -h "$RUN_ROOT"
  } > "$METADATA_DIR/df-h.txt"

  if [[ $CAPTURED_DOCTOR -eq 0 ]]; then
    "${BGPERF_CMD[@]}" doctor > "$METADATA_DIR/doctor.txt" 2>&1 || true
    CAPTURED_DOCTOR=1
  fi
  if [[ $CAPTURED_IMAGES -eq 0 ]]; then
    "${BGPERF_CMD[@]}" images > "$METADATA_DIR/images.txt" 2>&1 || true
    CAPTURED_IMAGES=1
  fi

  SUITE_TEXT="$suite_list" CONFIG_TEXT="$config_list" MRT_OVERRIDE_VALUE="$MRT_FILE" "$PYTHON_BIN" - "$METADATA_DIR/manifest.json" "$RUN_ID" "$RUN_ROOT" "$WORKDIR" "$RESULTS_ROOT" <<'PY'
import json
import os
import platform
import sys
from datetime import datetime, timezone

manifest_path, run_id, run_root, workdir, results_root = sys.argv[1:6]
suites = [s for s in os.environ.get("SUITE_TEXT", "").splitlines() if s]
configs = [c for c in os.environ.get("CONFIG_TEXT", "").splitlines() if c]
mrt_override = os.environ.get("MRT_OVERRIDE_VALUE") or None

mrt_files = set()
for config_path in configs:
    with open(config_path, "r", encoding="utf-8") as config_file:
        for line in config_file:
            stripped = line.strip()
            if stripped.startswith("mrt_file:"):
                mrt_files.add(stripped.split(":", 1)[1].strip())

now = datetime.now(timezone.utc).isoformat()
existing = {}
if os.path.exists(manifest_path):
    with open(manifest_path, "r", encoding="utf-8") as f:
        existing = json.load(f)

manifest = {
    "timestamp_utc": existing.get("timestamp_utc", now),
    "last_updated_utc": now,
    "run_id": run_id,
    "run_root": run_root,
    "results_root": results_root,
    "workdir": workdir,
    "cwd": os.getcwd(),
    "hostname": platform.node(),
    "user": os.environ.get("USER"),
    "suites": sorted(set(existing.get("suites", [])) | set(suites)),
    "rendered_config_paths": sorted(
        set(existing.get("rendered_config_paths", [])) | set(configs)
    ),
    "mrt_files": sorted(set(existing.get("mrt_files", [])) | mrt_files),
    "mrt_override": mrt_override or existing.get("mrt_override"),
}
with open(manifest_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, sort_keys=True)
    f.write("\n")
PY
}

rendered_configs=()
preflight_args=(--workdir "$WORKDIR" --run-root "$RUN_ROOT")
for suite in "${SUITES[@]}"; do
  cfg="$(suite_config "$suite")"
  rendered="$RENDERED_CONFIG_DIR/$suite.yaml"
  render_config "$suite" "$cfg" "$rendered"
  rendered_configs+=("$rendered")
  preflight_args+=(--config "$rendered")
done

capture_metadata

scripts/preflight_2026_suite.sh "${preflight_args[@]}"

for suite in "${SUITES[@]}"; do
  cfg="$RENDERED_CONFIG_DIR/$suite.yaml"
  suite_dir="$RUN_ROOT/$suite"
  complete_marker="$suite_dir/COMPLETE"
  mkdir -p "$suite_dir"

  if [[ -f "$complete_marker" && $FORCE -eq 0 ]]; then
    echo "Skipping completed suite: $suite"
    continue
  fi

  echo "Running suite: $suite"
  resume_args=(--resume)
  if [[ $FORCE -eq 1 ]]; then
    resume_args=()
  fi
  "${BGPERF_CMD[@]}" -d "$WORKDIR" batch -c "$cfg" --results-dir "$suite_dir" \
    "${resume_args[@]}" \
    > "$LOG_DIR/$suite.stdout.log" 2> "$LOG_DIR/$suite.stderr.log"

  touch "$complete_marker"
done

echo "All requested suites processed under $RUN_ROOT"
