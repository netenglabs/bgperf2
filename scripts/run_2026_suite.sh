#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

# The workdir guards, the recorded-workdir refusal, the config snapshot and the
# manifest writer are shared with scripts/run_timing_validation_block.sh. See
# that file's header for why they are not duplicated.
# shellcheck source=lib/campaign_common.sh
source "$SCRIPT_DIR/lib/campaign_common.sh"

usage() {
  cat <<'EOF'
Usage:
  scripts/run_2026_suite.sh <next|all|smoke|core-synth|core-mrt|filters
                            |calibration-synth|calibration-mrt> [options]

  The calibration suites are Phase 6 measurement calibration, not campaign
  work: 'all' and 'next' do not include them, and they take no COMPLETE
  marker into account. They are here so they run through the same preflight
  and work directory as everything else.

Options:
  --run-id ID           Stable run ID for results/2026/<run-id>
  --results-root DIR    Root for run directories (default: results/2026)
  --workdir DIR         Benchmark work directory. Defaults to /data/bgperf-work
                        when /data is a filesystem of its own; required
                        otherwise, since the alternative is guessing at the
                        root filesystem.
  --mrt-file PATH       Override every mrt_file: entry in selected suites
  --force               Re-run suites even if COMPLETE marker exists
  --allow-root-workdir  Proceed even though the work directory is on the root
                        filesystem. Two cases need it: a host that genuinely
                        has one filesystem (--workdir is still required there),
                        and honouring a manifest that recorded such a path for
                        a run already in flight. On the campaign host with
                        neither of those, it means /data did not mount.
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
WORKDIR="$(campaign_default_workdir)"
ALLOW_ROOT_WORKDIR=0
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
    --allow-root-workdir)
      ALLOW_ROOT_WORKDIR=1
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

PYTHON_BIN="$(campaign_choose_python)"
BGPERF_CMD=("$PYTHON_BIN" "bgperf2.py")

# A distinct results/snapshot key per invocation for calibration, the suite
# name itself for campaign work.
INVOCATION_STAMP="$(date +%Y%m%d-%H%M%S)"

suite_key() {
  if [[ $(is_calibration_suite "$1") -eq 1 ]]; then
    echo "$1-$INVOCATION_STAMP"
  else
    echo "$1"
  fi
}

is_calibration_suite() {
  case "$1" in
    calibration-synth|calibration-mrt) echo 1 ;;
    *) echo 0 ;;
  esac
}

suite_config() {
  case "$1" in
    smoke) echo "benchmarks/2026-smoke.yaml" ;;
    core-synth) echo "benchmarks/2026-core-synth.yaml" ;;
    core-mrt) echo "benchmarks/2026-core-mrt.yaml" ;;
    filters) echo "benchmarks/2026-filters.yaml" ;;
    calibration-synth) echo "benchmarks/2026-calibration-synth.yaml" ;;
    calibration-mrt) echo "benchmarks/2026-calibration-mrt.yaml" ;;
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

campaign_require_workdir "$WORKDIR"
campaign_guard_workdir "$WORKDIR" "$ALLOW_ROOT_WORKDIR"

campaign_validate_run_id "$RUN_ID"

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

# Before anything is created. A refusal that fires after `mkdir -p "$WORKDIR"`
# has already left an empty directory on whatever filesystem was named --
# including the root filesystem the default exists to avoid -- so the check
# that decides whether this invocation may proceed runs first.
campaign_check_recorded_workdir "$PYTHON_BIN" "$METADATA_DIR/manifest.json" "$WORKDIR"

mkdir -p "$RUN_ROOT" "$METADATA_DIR" "$ORIGINAL_CONFIG_DIR" "$RENDERED_CONFIG_DIR" "$LOG_DIR" "$WORKDIR"

echo "Run ID: $RUN_ID"
echo "Run root: $RUN_ROOT"
echo "Workdir: $WORKDIR"
if [[ -n "$MRT_FILE" ]]; then
  echo "MRT override: $MRT_FILE"
fi

CAPTURED_DOCTOR=0
CAPTURED_IMAGES=0

capture_metadata() {
  local suite_list
  local suite_keys=()
  local s
  for s in "${SUITES[@]}"; do
    suite_keys+=("$(suite_key "$s")")
  done
  suite_list="$(printf '%s\n' "${suite_keys[@]}")"
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

  SUITE_TEXT="$suite_list" CONFIG_TEXT="$config_list" MRT_OVERRIDE_VALUE="$MRT_FILE" \
    campaign_write_manifest "$PYTHON_BIN" "$METADATA_DIR/manifest.json" \
      "$RUN_ID" "$RUN_ROOT" "$WORKDIR" "$RESULTS_ROOT"
}

rendered_configs=()
preflight_args=(--workdir "$WORKDIR" --run-root "$RUN_ROOT")
for suite in "${SUITES[@]}"; do
  key="$(suite_key "$suite")"
  cfg="$(suite_config "$suite")"
  rendered="$RENDERED_CONFIG_DIR/$key.yaml"
  campaign_render_config "$key" "$cfg" "$rendered"
  rendered_configs+=("$rendered")
  preflight_args+=(--config "$rendered")
done

capture_metadata

scripts/preflight_2026_suite.sh "${preflight_args[@]}"

for suite in "${SUITES[@]}"; do
  key="$(suite_key "$suite")"
  cfg="$RENDERED_CONFIG_DIR/$key.yaml"
  suite_dir="$RUN_ROOT/$key"
  complete_marker="$suite_dir/COMPLETE"
  mkdir -p "$suite_dir"

  # Calibration is the one thing an operator reruns -- its whole job is to be
  # repeated when something changes -- so it takes no COMPLETE marker in either
  # direction. Dropping the marker is not on its own enough: `batch --resume`
  # records every cell in <test>.progress.json *including FAILED ones*, so a
  # rerun into the same directory would skip all three failed passes and exit 0
  # having done nothing. That is why a calibration suite gets its own
  # timestamped results directory per invocation (see suite_key) -- a fresh
  # directory has no progress file to resume from and no snapshot to collide
  # with, which is also what lets an operator edit the config and rerun the
  # same command.
  if [[ $(is_calibration_suite "$suite") -eq 0 ]]; then
    if [[ -f "$complete_marker" && $FORCE -eq 0 ]]; then
      echo "Skipping completed suite: $suite"
      continue
    fi
  fi

  echo "Running suite: $suite"
  resume_args=(--resume)
  if [[ $FORCE -eq 1 ]]; then
    resume_args=()
  fi
  "${BGPERF_CMD[@]}" -d "$WORKDIR" batch -c "$cfg" --results-dir "$suite_dir" \
    "${resume_args[@]}" \
    > "$LOG_DIR/$key.stdout.log" 2> "$LOG_DIR/$key.stderr.log"

  if [[ $(is_calibration_suite "$suite") -eq 0 ]]; then
    touch "$complete_marker"
  fi
done

echo "All requested suites processed under $RUN_ROOT"
