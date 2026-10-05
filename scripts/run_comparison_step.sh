#!/usr/bin/env bash
set -euo pipefail

# Launch one 2026 daemon comparison batch (docs/2026-daemon-comparison-plan.md
# §9) detached, on the host class Phase 5 measures on, and return at once.
#
# It exists because the hand-typed command has two ways to quietly ruin a
# step. Run on the wrong host, it measures rows that cannot sit on the curve:
# Phase 5's rows are all from one m7a.8xlarge, and a reclaimed spot instance
# comes back as whatever was available. Run without --resume after an
# interruption, `batch` unlinks the test's progress and summary documents
# before its first cell, and the finished rows' order and seed go with them.
# So the host is checked, and a step with a progress file on disk is resumed
# unless --fresh says otherwise.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

# shellcheck source=lib/campaign_common.sh
source "$SCRIPT_DIR/lib/campaign_common.sh"

# Phase 5's host: the m7a.8xlarge of plan §6/§9.
EXPECTED_MODEL="AMD EPYC 9R14"
EXPECTED_CPUS=32
# 123.12 GB is what bgperf2 records for it; 120 GiB leaves room for the
# kernel's reservation without admitting the 64 GB class.
MIN_MEM_KB=$((120 * 1024 * 1024))

usage() {
  cat <<'EOF'
Usage:
  scripts/run_comparison_step.sh [CONFIG] [--fresh]

  CONFIG defaults to benchmarks/2026-comparison-rrc00-n38.yaml. Its results go
  to results/2026/2026-comparison/<name without "2026-comparison-">/, and its
  logs to /data/bgperf-work/logs/<test name>-<UTC timestamp>.*.

  A step any of whose tests has a progress file is resumed (`batch --resume`): completed
  cells are skipped and the recorded order continues. --fresh starts it over
  instead, which discards that step's progress and summary documents.
EOF
}

CONFIG="benchmarks/2026-comparison-rrc00-n38.yaml"
FRESH=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --fresh) FRESH=1 ;;
    -*) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    *) CONFIG="$1" ;;
  esac
  shift
done

fail() { echo "REFUSED: $*" >&2; exit 1; }

[[ -f "$CONFIG" ]] || fail "no config at $CONFIG"
NAME="$(basename "$CONFIG" .yaml)"
[[ "$NAME" == 2026-comparison-* ]] || fail "$CONFIG is not a 2026-comparison config"
RESULTS_DIR="results/2026/2026-comparison/${NAME#2026-comparison-}"

# The host.
model="$(lscpu | sed -n 's/^Model name:[[:space:]]*//p')"
cpus="$(nproc --all)"
tpc="$(lscpu | sed -n 's/^Thread(s) per core:[[:space:]]*//p')"
mem_kb="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
echo "host: $model, $cpus CPUs, $tpc thread(s) per core, $((mem_kb / 1024 / 1024)) GiB"
[[ "$model" == "$EXPECTED_MODEL" ]] || fail "CPU is '$model', not $EXPECTED_MODEL"
[[ "$cpus" -eq "$EXPECTED_CPUS" ]] || fail "$cpus CPUs, not $EXPECTED_CPUS (the m7a.8xlarge)"
[[ "$tpc" == "1" ]] || fail "$tpc threads per core, not 1"
[[ "$mem_kb" -ge "$MIN_MEM_KB" ]] || fail "$((mem_kb / 1024 / 1024)) GiB of memory, the m7a.8xlarge has 123"

# The work directory, by the same rule as the campaign runners.
WORKDIR="$(campaign_default_workdir)"
campaign_require_workdir "$WORKDIR"
campaign_guard_workdir "$WORKDIR"

# Nothing else may share the host with a benchmark.
# Anchored to an interpreter running bench or batch. Unanchored, it matches
# an editor on bgperf2.py, and any shell whose command line merely contains
# the text -- including the one checking.
RUNNING='^[^ ]*python[0-9.]* ([^ ]*/)?bgperf2\.py .*\b(bench|batch)\b'
if pgrep -f "$RUNNING" >/dev/null; then
  pgrep -af "$RUNNING" >&2
  fail "a bgperf2.py is already running"
fi

# Every mrt_file the config names must be here; a fresh host may lack the
# decompressed bview.
while read -r mrt; do
  [[ -f "$mrt" ]] || fail "$CONFIG names $mrt, which is not on this host"
done < <(sed -n 's/^[[:space:]]*mrt_file:[[:space:]]*//p' "$CONFIG" | sort -u)

PYTHON_BIN="$(campaign_choose_python)"

# `batch` names each progress file after its test, not after the config, and
# a config can hold several tests. Any one of them on disk means the config
# has run, and a launch without --resume would delete them all.
mapfile -t TESTS < <("$PYTHON_BIN" -c '
import sys, yaml
for t in yaml.safe_load(open(sys.argv[1]))["tests"]:
    print(t["name"])' "$CONFIG")
[[ "${#TESTS[@]}" -gt 0 ]] || fail "$CONFIG names no tests"
PROGRESS=()
for t in "${TESTS[@]}"; do
  if [[ -f "$RESULTS_DIR/$t.progress.json" ]]; then
    PROGRESS+=("$RESULTS_DIR/$t.progress.json")
  fi
done

RESUME=()
if [[ "${#PROGRESS[@]}" -gt 0 ]]; then
  if [[ "$FRESH" -eq 1 ]]; then
    echo "--fresh: starting $NAME over; its progress and summary are discarded"
  else
    RESUME=(--resume)
    echo "resuming $NAME from ${PROGRESS[*]}"
  fi
fi

mkdir -p "$WORKDIR/logs"
LOG="$WORKDIR/logs/$NAME-$(date -u +%Y%m%dT%H%M%S)"
setsid nohup "$PYTHON_BIN" bgperf2.py -d "$WORKDIR" batch -c "$CONFIG" \
  --results-dir "$RESULTS_DIR" "${RESUME[@]}" \
  > "$LOG.stdout.log" 2> "$LOG.stderr.log" < /dev/null &
# Not $!: setsid forks when its caller leads a process group, and then $! is a
# wrapper that exits at once, so a watcher on it reports a running batch as
# finished. Ask for the batch itself.
sleep 3
pid="$(pgrep -nf "^[^ ]*python[0-9.]* bgperf2\.py -d $WORKDIR batch -c $CONFIG")" \
  || fail "the batch exited at once; see $LOG.stderr.log"
echo "$pid" > "$LOG.pid"

echo "launched at $(date -u +%H:%M) UTC on $(git -C "$REPO_ROOT" rev-parse --short HEAD), pid $(cat "$LOG.pid")"
echo "log:      $LOG.{stdout,stderr}.log"
echo "results:  $RESULTS_DIR/"
for t in "${TESTS[@]}"; do
  echo "progress: python3 -c \"import json; print(len(json.load(open('$RESULTS_DIR/$t.progress.json'))['cells']), 'rows done')\""
done
echo "running:  [ -d /proc/$(cat "$LOG.pid") ] && echo running || echo finished"
