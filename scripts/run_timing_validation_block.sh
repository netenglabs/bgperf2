#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

# The workdir guards, the recorded-workdir refusal, the config snapshot and the
# manifest writer are shared with scripts/run_2026_suite.sh.
# shellcheck source=lib/campaign_common.sh
source "$SCRIPT_DIR/lib/campaign_common.sh"

usage() {
  cat <<'EOF'
Usage:
  scripts/run_timing_validation_block.sh <next|list|status|block-N|accept> [options]

Runs the 64 GB timing validation campaign
(docs/2026-64gb-timing-validation-plan.md) one execution block at a time.

Actions:
  next        Run the first block that has not been accepted
  block-N     Run block N specifically (0 through 11)
  list        Print the block order and what each one is
  status      Print each block's durable state under this run ID
  accept N    Record block N as reviewed and accepted, after you have read its
              evidence. This is what `next` advances past.

Two markers, not one. A block writes RAN when its mechanical work finished,
and only an operator's `accept` writes COMPLETE. The campaign contract says a
block is finished when it has been *reviewed*, and a single marker written by
the runner would let a session that died between the batch and the review look
exactly like one that reviewed it.

Options:
  --run-id ID           Default: 2026-timing-validation (the campaign identity)
  --results-root DIR    Default: results/2026
  --workdir DIR         Default: /data/bgperf-work when /data is its own
                        filesystem; required otherwise.
  --mrt-file PATH       Override every mrt_file: entry in this block's configs
  --note TEXT           Recorded in the COMPLETE marker (accept only)
  --force               Re-measure a block, discarding its previous results,
                        markers and batch progress
  --allow-root-workdir  Proceed with a work directory on the root filesystem
  -h, --help            Show this help
EOF
}

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 1
fi

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

ACTION="$1"
shift

# The campaign's Fixed Campaign Identity. Defaults rather than constants: an
# operator reproducing a block elsewhere needs to be able to point it at a
# different run root, and a wrong default is easier to notice than a hardcoded
# path that ignores the flag.
RUN_ID="2026-timing-validation"
RESULTS_ROOT="results/2026"
WORKDIR="$(campaign_default_workdir)"
ALLOW_ROOT_WORKDIR=0
MRT_FILE=""
NOTE=""
FORCE=0
ACCEPT_TARGET=""

# `accept 3` takes its block number positionally, before the options.
if [[ "$ACTION" == "accept" && $# -gt 0 && "$1" != --* ]]; then
  ACCEPT_TARGET="$1"
  shift
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-id) RUN_ID="${2:?missing value for --run-id}"; shift 2 ;;
    --results-root) RESULTS_ROOT="${2:?missing value for --results-root}"; shift 2 ;;
    --workdir) WORKDIR="${2:?missing value for --workdir}"; shift 2 ;;
    --mrt-file) MRT_FILE="${2:?missing value for --mrt-file}"; shift 2 ;;
    --note) NOTE="${2:?missing value for --note}"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --allow-root-workdir) ALLOW_ROOT_WORKDIR=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

# The plan's Execution Blocks, in the plan's own order. The key is the
# directory name under the run root; nothing here may be reordered or renamed
# without renaming a directory some earlier block already wrote into.
BLOCK_KEYS=(
  block0-preflight-and-smoke
  block1-generator-calibration
  block2-synthetic-rep1
  block3-synthetic-rep2
  block4-synthetic-rep3
  block5-mrt-rep1
  block6-mrt-rep2
  block7-mrt-rep3
  block8-bird-architecture-screen
  block9-variance-review
  block10-selected-repetitions
  block11-final-report
)
BLOCK_TITLES=(
  "preflight and timing smoke"
  "generator calibration"
  "high-load synthetic repetition 1 of 3"
  "high-load synthetic repetition 2 of 3"
  "high-load synthetic repetition 3 of 3"
  "full-internet MRT repetition 1 of 3"
  "full-internet MRT repetition 2 of 3"
  "full-internet MRT repetition 3 of 3"
  "BIRD architecture screen"
  "variance, version, and BIRD-screen review"
  "selected repetitions"
  "final report"
)

parse_block_number() {
  local raw="$1"
  local number="${raw#block-}"
  number="${number#block}"
  # Base 10 explicitly. `(( 010 ))` is octal in bash, so a zero-padded argument
  # passed the regex and then named a different block: `accept 010` accepted
  # block 8, and `accept 08` failed the arithmetic while still being accepted
  # as valid.
  if [[ ! "$number" =~ ^[0-9]+$ ]] || (( 10#$number >= ${#BLOCK_KEYS[@]} )); then
    echo "no such block: $raw (0 through $(( ${#BLOCK_KEYS[@]} - 1 )))" >&2
    return 1
  fi
  echo "$(( 10#$number ))"
}

PYTHON_BIN="$(campaign_choose_python)"
BGPERF_CMD=("$PYTHON_BIN" "bgperf2.py")

campaign_validate_run_id "$RUN_ID"
RUN_ROOT="${RESULTS_ROOT%/}/$RUN_ID"
METADATA_DIR="$RUN_ROOT/metadata"
CONFIG_SNAPSHOT_DIR="$METADATA_DIR/configs"
ORIGINAL_CONFIG_DIR="$CONFIG_SNAPSHOT_DIR/original"
RENDERED_CONFIG_DIR="$CONFIG_SNAPSHOT_DIR/rendered"
LOG_DIR="$METADATA_DIR/logs"

block_state() {
  local index="$1"
  local dir="$RUN_ROOT/${BLOCK_KEYS[$index]}"
  if [[ -f "$dir/COMPLETE" ]]; then
    echo "complete"
  elif [[ -f "$dir/RAN" ]]; then
    echo "awaiting-review"
  elif [[ -d "$dir" ]]; then
    echo "started"
  else
    echo "not-started"
  fi
}

if [[ "$ACTION" == "list" ]]; then
  for i in "${!BLOCK_KEYS[@]}"; do
    printf 'block-%-2s %-34s %s\n' "$i" "${BLOCK_KEYS[$i]}" "${BLOCK_TITLES[$i]}"
  done
  exit 0
fi

if [[ "$ACTION" == "status" ]]; then
  echo "Run root: $RUN_ROOT"
  for i in "${!BLOCK_KEYS[@]}"; do
    printf 'block-%-2s %-34s %s\n' "$i" "${BLOCK_KEYS[$i]}" "$(block_state "$i")"
  done
  exit 0
fi

if [[ "$ACTION" == "accept" ]]; then
  if [[ -z "$ACCEPT_TARGET" ]]; then
    echo "accept needs a block number: accept 0" >&2
    exit 1
  fi
  index="$(parse_block_number "$ACCEPT_TARGET")"
  dir="$RUN_ROOT/${BLOCK_KEYS[$index]}"
  if [[ ! -f "$dir/RAN" ]]; then
    # Accepting a block that never ran would write the marker `next` advances
    # past, and the campaign would skip the work believing it done.
    echo "block-$index has not run yet: no $dir/RAN" >&2
    exit 1
  fi
  if [[ -f "$dir/COMPLETE" ]]; then
    echo "block-$index is already accepted:"
    cat "$dir/COMPLETE"
    exit 0
  fi
  {
    echo "block: ${BLOCK_KEYS[$index]}"
    echo "title: ${BLOCK_TITLES[$index]}"
    echo "accepted_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "accepted_by: ${USER:-unknown}"
    echo "revision: $(git -C . rev-parse HEAD)"
    if [[ -n "$NOTE" ]]; then
      echo "note: $NOTE"
    fi
  } > "$dir/COMPLETE"
  echo "Accepted block-$index"
  cat "$dir/COMPLETE"
  exit 0
fi

if [[ "$ACTION" == "next" ]]; then
  BLOCK_INDEX=""
  for i in "${!BLOCK_KEYS[@]}"; do
    if [[ ! -f "$RUN_ROOT/${BLOCK_KEYS[$i]}/COMPLETE" ]]; then
      BLOCK_INDEX="$i"
      break
    fi
  done
  if [[ -z "$BLOCK_INDEX" ]]; then
    echo "Campaign is complete: $RUN_ROOT"
    exit 0
  fi
  state="$(block_state "$BLOCK_INDEX")"
  if [[ "$state" == "awaiting-review" && $FORCE -eq 0 ]]; then
    cat >&2 <<MSG
block-$BLOCK_INDEX (${BLOCK_TITLES[$BLOCK_INDEX]}) has already run and is waiting to be reviewed.

Read its evidence under $RUN_ROOT/${BLOCK_KEYS[$BLOCK_INDEX]}, then:
  scripts/run_timing_validation_block.sh accept $BLOCK_INDEX --note "..."

Re-running it instead would discard an observation that was already paid for;
pass --force if that is really what you mean.
MSG
    exit 1
  fi
  echo "Next block: block-$BLOCK_INDEX (${BLOCK_TITLES[$BLOCK_INDEX]})"
else
  BLOCK_INDEX="$(parse_block_number "$ACTION")"
fi

BLOCK_KEY="${BLOCK_KEYS[$BLOCK_INDEX]}"
BLOCK_DIR="$RUN_ROOT/$BLOCK_KEY"

if [[ -f "$BLOCK_DIR/COMPLETE" && $FORCE -eq 0 ]]; then
  echo "block-$BLOCK_INDEX is already accepted; pass --force to run it again" >&2
  exit 1
fi
if [[ -f "$BLOCK_DIR/RAN" && $FORCE -eq 0 ]]; then
  echo "block-$BLOCK_INDEX has already run and is waiting for review" >&2
  echo "accept it, or pass --force to run it again" >&2
  exit 1
fi

campaign_require_workdir "$WORKDIR"
campaign_guard_workdir "$WORKDIR" "$ALLOW_ROOT_WORKDIR"

# Never two at once. The campaign contract's "never run cells or blocks
# concurrently" is not advisory: two blocks share one Docker bridge naming
# scheme and one set of fixed container names, so the second would remove the
# first's target mid-run and publish both results as though nothing happened.
LOCK_FILE="$RUN_ROOT/.block.lock"
mkdir -p "$RUN_ROOT"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "another block is running under $RUN_ROOT (lock: $LOCK_FILE)" >&2
  exit 1
fi

campaign_check_recorded_workdir "$PYTHON_BIN" "$METADATA_DIR/manifest.json" "$WORKDIR"

mkdir -p "$METADATA_DIR" "$ORIGINAL_CONFIG_DIR" "$RENDERED_CONFIG_DIR" \
         "$LOG_DIR" "$BLOCK_DIR" "$WORKDIR"

echo "Run ID: $RUN_ID"
echo "Run root: $RUN_ROOT"
echo "Block: $BLOCK_KEY"
echo "Workdir: $WORKDIR"
if [[ -n "$MRT_FILE" ]]; then
  echo "MRT override: $MRT_FILE"
fi

MRT_INPUT="${MRT_FILE:-mrt/rib.20260808.0000}"

capture_metadata() {
  local configs=("$@")
  local config_list
  config_list="$(printf '%s\n' "${configs[@]}")"

  git -C . rev-parse HEAD > "$METADATA_DIR/git-rev-parse-head.txt"
  git -C . status --short > "$METADATA_DIR/git-status-short.txt"
  uname -a > "$METADATA_DIR/uname-a.txt"
  free -h > "$METADATA_DIR/free-h.txt"
  {
    df -h "$WORKDIR"
    df -h "$RUN_ROOT"
  } > "$METADATA_DIR/df-h.txt"
  "${BGPERF_CMD[@]}" doctor > "$METADATA_DIR/doctor.txt" 2>&1 || true
  "${BGPERF_CMD[@]}" images > "$METADATA_DIR/images.txt" 2>&1 || true

  local facts
  facts="$("$PYTHON_BIN" scripts/campaign_host_facts.py "$MRT_INPUT")"
  # Under one key so the block's facts cannot collide with the manifest's own
  # spine, and per block because images are rebuilt and hosts are resized
  # between them: one shared record would describe whichever block wrote last.
  local extra
  extra="$(FACTS="$facts" BLOCK_KEY="$BLOCK_KEY" BLOCK_INDEX="$BLOCK_INDEX" \
    BLOCK_TITLE="${BLOCK_TITLES[$BLOCK_INDEX]}" "$PYTHON_BIN" - <<'PY'
import json
import os
facts = json.loads(os.environ["FACTS"])
facts["block_index"] = int(os.environ["BLOCK_INDEX"])
facts["block_title"] = os.environ["BLOCK_TITLE"]
print(json.dumps({"blocks": {os.environ["BLOCK_KEY"]: facts}}))
PY
)"
  # A manifest already carrying another block's facts must keep them: the
  # merge is per run ID, and "blocks" is one key.
  extra="$(EXTRA="$extra" MANIFEST="$METADATA_DIR/manifest.json" "$PYTHON_BIN" - <<'PY'
import json
import os
extra = json.loads(os.environ["EXTRA"])
path = os.environ["MANIFEST"]
existing = {}
if os.path.exists(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            existing = json.load(f).get("blocks") or {}
    except (OSError, ValueError):
        existing = {}
merged = dict(existing)
merged.update(extra["blocks"])
print(json.dumps({"blocks": merged}))
PY
)"

  SUITE_TEXT="$BLOCK_KEY" CONFIG_TEXT="$config_list" \
  MRT_OVERRIDE_VALUE="$MRT_FILE" MANIFEST_EXTRA_JSON="$extra" \
    campaign_write_manifest "$PYTHON_BIN" "$METADATA_DIR/manifest.json" \
      "$RUN_ID" "$RUN_ROOT" "$WORKDIR" "$RESULTS_ROOT"
}

# A forced run replaces this block's results, so it retracts the claims made
# about the old ones. Left in place, COMPLETE would say the new rows had been
# reviewed -- `block_state()` reads it before RAN, so `status` would report
# `complete` and `next` would skip the block -- and `accept` would decline to
# repair it, since it sees a block already accepted. That is the failure the
# two markers exist to prevent, reached from the other side.
#
# Called where the results actually start being replaced, not beside the
# checks that let --force past the markers: everything before this point can
# still turn the run away -- the workdir guard, the lock, the recorded-workdir
# refusal, `verify`, the MRT validation -- and a run that replaced nothing must
# not have deleted the acceptance record of what is still there.
retract_forced_markers() {
  if [[ $FORCE -eq 1 ]]; then
    rm -f "$BLOCK_DIR/COMPLETE" "$BLOCK_DIR/RAN"
  fi
}

run_batch() {
  local key="$1"
  local out_dir="$2"
  local rendered="$RENDERED_CONFIG_DIR/$key.yaml"
  mkdir -p "$out_dir"
  echo "Running $key -> $out_dir"
  # --resume is what makes an interrupted block resumable, and it is exactly
  # wrong under --force: `batch --resume` records every completed cell in
  # <test>.progress.json, so a forced re-run would skip all of them, exit 0
  # having measured nothing, and the block would then stamp the *old*
  # artifacts with the current revision and ask an operator to accept rows
  # nobody re-measured. The sibling runner drops it for the same reason.
  local resume_args=(--resume)
  if [[ $FORCE -eq 1 ]]; then
    resume_args=()
  fi
  "${BGPERF_CMD[@]}" -d "$WORKDIR" batch -c "$rendered" \
    --results-dir "$out_dir" "${resume_args[@]}" \
    > "$LOG_DIR/$key.stdout.log" 2> "$LOG_DIR/$key.stderr.log"
}

# Every block that runs benchmarks qualifies its own rows before it claims to
# have run: a block whose evidence nobody checked is a block whose exit
# criterion nobody applied, and the plan's is mechanical.
#
# A failing check is counted, not raised. Under `set -euo pipefail` a checker
# that exits non-zero would abort the script where it stands, so the *second*
# smoke's evidence would never be written at all -- half the block's record
# lost to the first failure, on a block whose whole output is that record.
# The count is read after every check has run, above the RAN marker.
EVIDENCE_FAILURES=0
check_evidence() {
  local out_dir="$1"
  local expect="$2"
  local label="$3"
  local status=0
  mkdir -p "$BLOCK_DIR/evidence"
  "$PYTHON_BIN" scripts/check_timing_evidence.py "$out_dir" \
    --expect "$expect" --json "$BLOCK_DIR/evidence/$label.json" \
    > "$BLOCK_DIR/evidence/$label.txt" 2>&1 || status=$?
  cat "$BLOCK_DIR/evidence/$label.txt"
  if [[ $status -ne 0 ]]; then
    EVIDENCE_FAILURES=$((EVIDENCE_FAILURES + 1))
    echo "evidence check FAILED for $label" >&2
  fi
}

case "$BLOCK_INDEX" in
  0)
    SYNTH_CONFIG="benchmarks/2026-timing-smoke-synth.yaml"
    MRT_CONFIG="benchmarks/2026-timing-smoke-mrt.yaml"
    campaign_render_config "block0-smoke-synth" "$SYNTH_CONFIG" \
      "$RENDERED_CONFIG_DIR/block0-smoke-synth.yaml"
    campaign_render_config "block0-smoke-mrt" "$MRT_CONFIG" \
      "$RENDERED_CONFIG_DIR/block0-smoke-mrt.yaml"
    capture_metadata "$RENDERED_CONFIG_DIR/block0-smoke-synth.yaml" \
                     "$RENDERED_CONFIG_DIR/block0-smoke-mrt.yaml"

    scripts/preflight_2026_suite.sh --workdir "$WORKDIR" --run-root "$RUN_ROOT" \
      --config "$RENDERED_CONFIG_DIR/block0-smoke-synth.yaml" \
      --config "$RENDERED_CONFIG_DIR/block0-smoke-mrt.yaml" \
      | tee "$METADATA_DIR/preflight.txt"

    # `verify` is the only check that puts a real container in front of each
    # parser, and it is where the version-reporting bugs have been. A campaign
    # whose provenance columns are wrong is a campaign of unattributable rows,
    # so this is fatal rather than captured-and-ignored.
    echo "Verifying built images"
    "${BGPERF_CMD[@]}" verify > "$METADATA_DIR/verify.txt" 2>&1 || {
      echo "verify failed; see $METADATA_DIR/verify.txt" >&2
      tail -20 "$METADATA_DIR/verify.txt" >&2
      exit 1
    }
    tail -5 "$METADATA_DIR/verify.txt"

    # The pinned RIB, read by bgpdump2 itself. The file's size is in the
    # manifest; this is the only thing that says the injectors can parse it.
    echo "Validating pinned MRT: $MRT_INPUT"
    scripts/prepare_mrt.sh "$MRT_INPUT" > "$METADATA_DIR/mrt-validation.txt" 2>&1 || {
      echo "MRT validation failed; see $METADATA_DIR/mrt-validation.txt" >&2
      tail -20 "$METADATA_DIR/mrt-validation.txt" >&2
      exit 1
    }
    tail -4 "$METADATA_DIR/mrt-validation.txt"

    retract_forced_markers
    run_batch "block0-smoke-synth" "$BLOCK_DIR/smoke-synth"
    run_batch "block0-smoke-mrt" "$BLOCK_DIR/smoke-mrt"

    check_evidence "$BLOCK_DIR/smoke-synth" 1 "smoke-synth"
    check_evidence "$BLOCK_DIR/smoke-mrt" 1 "smoke-mrt"
    ;;
  *)
    cat >&2 <<MSG
block-$BLOCK_INDEX (${BLOCK_TITLES[$BLOCK_INDEX]}) is not built yet.

Each block's configs and procedure are its own change set, written when the
campaign reaches it -- see docs/2026-64gb-timing-validation-plan.md, section
"Execution Blocks". Nothing here should invent one: a block that ran the wrong
matrix would produce rows that look exactly like the right ones.
MSG
    exit 2
    ;;
esac

if [[ $EVIDENCE_FAILURES -gt 0 ]]; then
  cat >&2 <<MSG

block-$BLOCK_INDEX did not meet its exit criterion: $EVIDENCE_FAILURES evidence check(s) failed.

The results and the verdicts are under $BLOCK_DIR; no RAN marker was written,
so the block is not offered for review. Read
$BLOCK_DIR/evidence/ and decide whether this is a run to
investigate or a rule to argue with.
MSG
  exit 1
fi

{
  echo "block: $BLOCK_KEY"
  echo "title: ${BLOCK_TITLES[$BLOCK_INDEX]}"
  echo "ran_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "revision: $(git -C . rev-parse HEAD)"
  echo "workdir: $WORKDIR"
} > "$BLOCK_DIR/RAN"

cat <<MSG

block-$BLOCK_INDEX ran. It is NOT complete until it is reviewed:

  read $BLOCK_DIR/evidence/
  then: scripts/run_timing_validation_block.sh accept $BLOCK_INDEX --note "..."
MSG
