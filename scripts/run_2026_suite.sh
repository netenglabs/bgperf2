#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

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
# Prefer a large separate volume, fall back to a path that exists everywhere.
# /var/tmp is on the root filesystem on most hosts -- 29 GB on the campaign
# host -- and a full-table MRT suite can fill it hours into a batch, taking
# journald and the root filesystem with it. Both operator contracts name
# /data/bgperf-work, and a default here that disagreed with them would be the
# one an operator actually gets, since --workdir is optional. But this script
# is checked in and runs on other machines, so the host-specific path is a
# preference and not a requirement: hardcoding it turns a fresh clone, or a
# replacement spot instance before its volume is mounted, into an immediate
# `mkdir -p` failure under `set -euo pipefail`.
filesystem_device() {
  # Empty when it cannot be answered, so a caller can tell "different device"
  # from "no idea" rather than having the two collapse into one comparison.
  stat -c %d "$1" 2>/dev/null || true
}

WORKDIR=""
ALLOW_ROOT_WORKDIR=0
# Writability is not the question -- an unmounted /data on a replacement spot
# instance is usually a present, empty, writable mount point *on the root
# filesystem*, which is precisely the 29 GB partition this default exists to
# stay off. What makes /data usable is that it is a different filesystem from
# /, so compare device numbers rather than permissions. The same test is
# applied to whatever --workdir resolves to, further down: guarding only the
# default would leave the check bypassed by the very invocation every operator
# contract now prints.
if [[ -d /data && -w /data ]]; then
  data_device="$(filesystem_device /data)"
  root_device_default="$(filesystem_device /)"
  # Both must answer. Two empties would compare equal and silently decline the
  # default; one empty would accept /data on the root filesystem as the default
  # -- the failure this test exists to catch.
  if [[ -n "$data_device" && -n "$root_device_default" \
        && "$data_device" != "$root_device_default" ]]; then
    WORKDIR="/data/bgperf-work"
  fi
fi
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

if [[ -z "$WORKDIR" ]]; then
  # No --workdir, and /data is not there to default to. Falling back to
  # /var/tmp would put a full-table MRT suite on the root filesystem of
  # whatever host this is -- 29 GB on the campaign host -- and fill it hours
  # into a batch, taking journald and the finished cells' artifacts with it.
  # That is the failure this default exists to avoid, so it is not something to
  # guess at: on a replacement spot instance whose /data volume is not mounted
  # yet, the quiet fallback is exactly the wrong answer.
  cat >&2 <<'MSG'
No --workdir given and /data is not available to default to.

Pass --workdir explicitly, on a filesystem with room for the suite: a
full-table MRT run puts bgpd.log alone past 1 GB per cell, and a suite runs
many of them. Do not point it at the root filesystem.
MSG
  exit 1
fi

# The same device test, on whatever we ended up with. A --workdir naming a path
# on the root filesystem is the identical hazard as a defaulted one, and it is
# the more likely of the two now that every contract prints an explicit
# --workdir: on a replacement instance whose /data never mounted,
# `--workdir /data/bgperf-work` creates a directory on the root and looks
# exactly like success. Refused rather than warned, because the warning would
# be one line in a batch that then runs for hours; --allow-root-workdir is
# there for a host that genuinely has one filesystem.
workdir_device_root="$WORKDIR"
while [[ -n "$workdir_device_root" && ! -e "$workdir_device_root" ]]; do
  workdir_device_root="$(dirname "$workdir_device_root")"
done
workdir_device="$(filesystem_device "$workdir_device_root")"
root_device="$(filesystem_device /)"
# An unanswerable check is not a passed one, and it is not a failed one either.
# Both sides come back empty on a host without GNU stat, and comparing two
# empty strings would refuse every invocation with a diagnosis that is simply
# wrong; comparing one empty against one real would wave through exactly the
# case this guard exists for. Say which of the two happened instead.
if [[ -z "$workdir_device" || -z "$root_device" ]]; then
  echo "WARNING: cannot determine whether $WORKDIR is on the root filesystem" >&2
  echo "         (stat -c is unavailable here). Proceeding without that check;" >&2
  echo "         make sure the work directory has room for the whole suite." >&2
elif [[ $ALLOW_ROOT_WORKDIR -eq 0 && "$workdir_device" == "$root_device" ]]; then
  cat >&2 <<MSG
Work directory $WORKDIR is on the root filesystem.

A suite writes every role's config and logs there -- a full-table MRT run puts
bgpd.log alone past 1 GB per cell -- and filling the root takes journald and
the finished cells' artifacts with it, hours into a batch.

If /data was expected to be mounted here, it is not. Pass --allow-root-workdir
if this host really has one filesystem, or if you are resuming a run whose
manifest recorded this path -- the recorded workdir wins, and honouring it is
the one case where landing on the root filesystem is the correct answer.
MSG
  exit 1
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

check_recorded_workdir() {
  local manifest="$METADATA_DIR/manifest.json"
  [[ -f "$manifest" ]] || return 0
  WORKDIR_ARG="$WORKDIR" "$PYTHON_BIN" - "$manifest" <<'WORKDIRCHECK' || exit 1
import json
import os
import sys

manifest_path = sys.argv[1]
invoked = os.path.abspath(os.path.normpath(os.environ["WORKDIR_ARG"]))
try:
    with open(manifest_path, "r", encoding="utf-8") as f:
        recorded_raw = json.load(f).get("workdir")
except (OSError, ValueError) as exc:
    # An unreadable manifest cannot be checked against, and bricking the run ID
    # over it is worse than proceeding -- but proceeding silently would hide
    # that the recorded-workdir guard did not run at all. capture_metadata
    # catches the same pair and rewrites; the two must agree or the one that
    # does not catch aborts the suite after directories have been created.
    sys.stderr.write(
        "WARNING: cannot read {0} ({1}); the recorded-workdir check is not "
        "being applied to this invocation.\n".format(manifest_path, exc))
    raise SystemExit(0)
if not recorded_raw:
    raise SystemExit(0)
if os.path.abspath(os.path.normpath(recorded_raw)) == invoked:
    raise SystemExit(0)
sys.stderr.write(
    "This run was recorded under workdir {0!r} but was invoked with {1!r}.\n"
    "The recorded one wins: re-run with --workdir {0}, or start a new run ID "
    "if you mean to change it.\n"
    "Refusing rather than writing a manifest that disagrees with where the "
    "logs go.\n".format(recorded_raw, os.environ["WORKDIR_ARG"]))
raise SystemExit(1)
WORKDIRCHECK
}

# Before anything is created. A refusal that fires after `mkdir -p "$WORKDIR"`
# has already left an empty directory on whatever filesystem was named --
# including the root filesystem the default exists to avoid -- so the check
# that decides whether this invocation may proceed runs first.
check_recorded_workdir

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

  SUITE_TEXT="$suite_list" CONFIG_TEXT="$config_list" MRT_OVERRIDE_VALUE="$MRT_FILE" "$PYTHON_BIN" - "$METADATA_DIR/manifest.json" "$RUN_ID" "$RUN_ROOT" "$WORKDIR" "$RESULTS_ROOT" <<'PY'
import json
import os
import platform
import sys
from datetime import datetime, timezone

manifest_path, run_id, run_root, workdir, results_root = sys.argv[1:6]
# The suite *keys*, not the bare names: a calibration suite writes to
# <suite>-<stamp>, and a manifest naming only "calibration-synth" could not
# be tied to either of two results directories under one run ID.
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
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except (OSError, ValueError):
        # A truncated manifest -- a filled disk or a kill inside the write
        # below -- must not brick the run ID with a traceback on every later
        # invocation. check_recorded_workdir already tolerates exactly this;
        # the two have to agree or the pre-check passes and this dies.
        sys.stderr.write(
            "WARNING: {0} is not readable JSON and is being rewritten from "
            "this invocation. Anything it recorded about earlier suites of "
            "this run ID is lost.\n".format(manifest_path))

# A recorded workdir is evidence, and this run is about to use whatever it was
# invoked with. Preserving the record while silently switching the directory is
# the worse of the two halves: the manifest would then disagree with the
# `df -h` captured beside it and with where the logs actually are. The campaign
# contract's rule is that the recorded manifest wins and the discrepancy is a
# finding to report, so this refuses rather than choosing either half.
recorded_workdir = existing.get("workdir")
if recorded_workdir and (os.path.abspath(os.path.normpath(recorded_workdir))
                         != os.path.abspath(os.path.normpath(workdir))):
    sys.stderr.write(
        "This run was recorded under workdir {0!r} but was invoked with "
        "{1!r}.\nThe recorded one wins: re-run with --workdir {0}, or start a "
        "new run ID if you mean to change it.\nRefusing rather than writing a "
        "manifest that disagrees with where the logs go.\n".format(
            recorded_workdir, workdir))
    raise SystemExit(1)

manifest = {
    "timestamp_utc": existing.get("timestamp_utc", now),
    "last_updated_utc": now,
    "run_id": run_id,
    "run_root": run_root,
    "results_root": results_root,
    # Unconditional is correct now: a mismatch has already been refused above,
    # so this can only ever be the value already recorded.
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
tmp_path = manifest_path + ".tmp"
with open(tmp_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, sort_keys=True)
    f.write("\n")
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp_path, manifest_path)
PY
}

rendered_configs=()
preflight_args=(--workdir "$WORKDIR" --run-root "$RUN_ROOT")
for suite in "${SUITES[@]}"; do
  key="$(suite_key "$suite")"
  cfg="$(suite_config "$suite")"
  rendered="$RENDERED_CONFIG_DIR/$key.yaml"
  render_config "$key" "$cfg" "$rendered"
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
