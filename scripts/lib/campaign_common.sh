#!/usr/bin/env bash
# Machinery shared by the campaign runners: scripts/run_2026_suite.sh (the
# 2026-baseline suite runner) and scripts/run_timing_validation_block.sh (the
# 64 GB timing validation block runner).
#
# It exists because the alternative is two copies of the same guards, and the
# first line of CLAUDE.md is about what a second copy of anything does: it
# fails silently. These guards are the ones that decide whether a multi-hour
# block writes its logs onto a 29 GB root filesystem, whether a resumed run
# honours the directory its own manifest recorded, and whether a run ID can be
# quietly fed two different benchmark inputs. A drifted copy of any of them is
# a campaign that looks like it ran correctly.
#
# Sourced, never executed. Functions take what they need as arguments, with one
# exception stated where it lives: campaign_render_config reads MRT_FILE,
# PYTHON_BIN, RUN_ID, ORIGINAL_CONFIG_DIR and RENDERED_CONFIG_DIR from the
# caller, because those five are the snapshot layout both runners already share
# under those names. Nothing else here does, and a new function should not.

# Empty when it cannot be answered, so a caller can tell "different device"
# from "no idea" rather than having the two collapse into one comparison.
campaign_filesystem_device() {
  stat -c %d "$1" 2>/dev/null || true
}

# Prefer a large separate volume, fall back to nothing at all.
# /var/tmp is on the root filesystem on most hosts -- 29 GB on the campaign
# host -- and a full-table MRT suite can fill it hours into a batch, taking
# journald and the root filesystem with it. Both operator contracts name
# /data/bgperf-work, and a default here that disagreed with them would be the
# one an operator actually gets, since --workdir is optional. But these
# scripts are checked in and run on other machines, so the host-specific path
# is a preference and not a requirement: hardcoding it turns a fresh clone, or
# a replacement spot instance before its volume is mounted, into an immediate
# `mkdir -p` failure under `set -euo pipefail`.
#
# Writability is not the question -- an unmounted /data on a replacement spot
# instance is usually a present, empty, writable mount point *on the root
# filesystem*, which is precisely the 29 GB partition this default exists to
# stay off. What makes /data usable is that it is a different filesystem from
# /, so compare device numbers rather than permissions. The same test is
# applied to whatever --workdir resolves to, in campaign_guard_workdir:
# guarding only the default would leave the check bypassed by the very
# invocation every operator contract now prints.
campaign_default_workdir() {
  local data_device root_device
  if [[ -d /data && -w /data ]]; then
    data_device="$(campaign_filesystem_device /data)"
    root_device="$(campaign_filesystem_device /)"
    # Both must answer. Two empties would compare equal and silently decline
    # the default; one empty would accept /data on the root filesystem as the
    # default -- the failure this test exists to catch.
    if [[ -n "$data_device" && -n "$root_device" \
          && "$data_device" != "$root_device" ]]; then
      echo "/data/bgperf-work"
    fi
  fi
}

# No --workdir, and /data was not there to default to. Falling back to
# /var/tmp would put a full-table MRT suite on the root filesystem of whatever
# host this is -- 29 GB on the campaign host -- and fill it hours into a
# batch, taking journald and the finished cells' artifacts with it. That is
# the failure this default exists to avoid, so it is not something to guess
# at: on a replacement spot instance whose /data volume is not mounted yet,
# the quiet fallback is exactly the wrong answer.
campaign_require_workdir() {
  local workdir="$1"
  if [[ -n "$workdir" ]]; then
    return 0
  fi
  cat >&2 <<'MSG'
No --workdir given and /data is not available to default to.

Pass --workdir explicitly, on a filesystem with room for the whole block: a
full-table MRT run puts bgpd.log alone past 1 GB per cell, and a block runs
many of them. Do not point it at the root filesystem.
MSG
  return 1
}

# The same device test, on whatever we ended up with. A --workdir naming a
# path on the root filesystem is the identical hazard as a defaulted one, and
# it is the more likely of the two now that every contract prints an explicit
# --workdir: on a replacement instance whose /data never mounted,
# `--workdir /data/bgperf-work` creates a directory on the root and looks
# exactly like success. Refused rather than warned, because the warning would
# be one line in a batch that then runs for hours; the allow_root argument is
# there for a host that genuinely has one filesystem.
campaign_guard_workdir() {
  local workdir="$1"
  local allow_root="${2:-0}"
  local probe workdir_device root_device

  probe="$workdir"
  while [[ -n "$probe" && ! -e "$probe" ]]; do
    probe="$(dirname "$probe")"
  done
  workdir_device="$(campaign_filesystem_device "$probe")"
  root_device="$(campaign_filesystem_device /)"

  # An unanswerable check is not a passed one, and it is not a failed one
  # either. Both sides come back empty on a host without GNU stat, and
  # comparing two empty strings would refuse every invocation with a diagnosis
  # that is simply wrong; comparing one empty against one real would wave
  # through exactly the case this guard exists for. Say which of the two
  # happened instead.
  if [[ -z "$workdir_device" || -z "$root_device" ]]; then
    echo "WARNING: cannot determine whether $workdir is on the root filesystem" >&2
    echo "         (stat -c is unavailable here). Proceeding without that check;" >&2
    echo "         make sure the work directory has room for the whole block." >&2
    return 0
  fi
  if [[ "$allow_root" -eq 0 && "$workdir_device" == "$root_device" ]]; then
    cat >&2 <<MSG
Work directory $workdir is on the root filesystem.

A block writes every role's config and logs there -- a full-table MRT run puts
bgpd.log alone past 1 GB per cell -- and filling the root takes journald and
the finished cells' artifacts with it, hours into a batch.

If /data was expected to be mounted here, it is not. Pass --allow-root-workdir
if this host really has one filesystem, or if you are resuming a run whose
manifest recorded this path -- the recorded workdir wins, and honouring it is
the one case where landing on the root filesystem is the correct answer.
MSG
    return 1
  fi
  return 0
}

# The run ID names a directory under the results root and is embedded in every
# path beneath it.
campaign_validate_run_id() {
  if [[ ! "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    echo "invalid run ID: use only letters, numbers, dots, underscores, and hyphens" >&2
    return 1
  fi
  return 0
}

campaign_choose_python() {
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
  return 1
}

# A recorded workdir is evidence, and this invocation is about to use whatever
# it was given. Checked before anything is created: a refusal that fires after
# `mkdir -p "$WORKDIR"` has already left an empty directory on whatever
# filesystem was named -- including the root filesystem the default exists to
# avoid.
campaign_check_recorded_workdir() {
  local python_bin="$1"
  local manifest="$2"
  local workdir="$3"
  [[ -f "$manifest" ]] || return 0
  WORKDIR_ARG="$workdir" "$python_bin" - "$manifest" <<'WORKDIRCHECK'
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
    # that the recorded-workdir guard did not run at all. The metadata capture
    # catches the same pair and rewrites; the two must agree or the one that
    # does not catch aborts the block after directories have been created.
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

# Snapshot the benchmark input this run is about to use, and refuse to let one
# run ID be fed two different ones. The rendered copy is what actually runs, so
# an --mrt-file override is visible in the snapshot rather than only in the
# command line that is gone by the time anyone reads the results.
#
# Globals read: MRT_FILE (may be empty), PYTHON_BIN, RUN_ID,
# ORIGINAL_CONFIG_DIR, RENDERED_CONFIG_DIR.
campaign_render_config() {
  local key="$1"
  local src="$2"
  local dst="$3"

  local original="$ORIGINAL_CONFIG_DIR/$key.yaml"
  local rendered_tmp
  rendered_tmp="$(mktemp "$RENDERED_CONFIG_DIR/$key.yaml.XXXXXX")"

  if [[ -f "$original" ]] && ! cmp -s "$src" "$original"; then
    echo "run ID $RUN_ID already has a different original config for $key" >&2
    echo "use a new run ID instead of mixing benchmark inputs" >&2
    rm -f "$rendered_tmp"
    return 1
  fi
  cp "$src" "$original"
  if [[ -z "${MRT_FILE:-}" ]]; then
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
    echo "run ID $RUN_ID already has a different rendered config for $key" >&2
    echo "use a new run ID instead of changing the MRT override" >&2
    rm -f "$rendered_tmp"
    return 1
  fi
  mv "$rendered_tmp" "$dst"
}

# Host and tool facts, captured beside the results rather than remembered.
#
# Arguments: manifest path, run ID, run root, workdir, results root.
# Environment: SUITE_TEXT and CONFIG_TEXT are newline-separated lists of the
# suite/block keys and rendered config paths this invocation is adding;
# MRT_OVERRIDE_VALUE is the --mrt-file override or empty; MANIFEST_EXTRA_JSON
# is an optional JSON object merged in at the top level, which is how a caller
# records facts of its own (the timing campaign's block identity, host CPU,
# Docker version, image identities and measurement schema) without a second
# manifest writer that could disagree with this one.
campaign_write_manifest() {
  local python_bin="$1"
  shift
  "$python_bin" - "$@" <<'PY'
import json
import os
import platform
import sys
from datetime import datetime, timezone

manifest_path, run_id, run_root, workdir, results_root = sys.argv[1:6]
# The suite/block *keys*, not the bare names: a calibration suite writes to
# <suite>-<stamp>, and a manifest naming only "calibration-synth" could not
# be tied to either of two results directories under one run ID.
suites = [s for s in os.environ.get("SUITE_TEXT", "").splitlines() if s]
configs = [c for c in os.environ.get("CONFIG_TEXT", "").splitlines() if c]
mrt_override = os.environ.get("MRT_OVERRIDE_VALUE") or None

extra_raw = os.environ.get("MANIFEST_EXTRA_JSON") or ""
extra = {}
if extra_raw.strip():
    try:
        extra = json.loads(extra_raw)
    except ValueError as exc:
        # Refuse rather than write a manifest missing the facts a caller
        # believes it recorded: a block whose manifest silently lacks its host
        # and image identities is a block that cannot be qualified later.
        sys.stderr.write(
            "MANIFEST_EXTRA_JSON is not valid JSON ({0}); refusing to write a "
            "manifest that would omit it.\n".format(exc))
        raise SystemExit(1)
    if not isinstance(extra, dict):
        sys.stderr.write(
            "MANIFEST_EXTRA_JSON must be a JSON object, got "
            "{0}.\n".format(type(extra).__name__))
        raise SystemExit(1)

now = datetime.now(timezone.utc).isoformat()
existing = {}
if os.path.exists(manifest_path):
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except (OSError, ValueError):
        # A truncated manifest -- a filled disk or a kill inside the write
        # below -- must not brick the run ID with a traceback on every later
        # invocation. campaign_check_recorded_workdir already tolerates exactly
        # this; the two have to agree or the pre-check passes and this dies.
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

# This file's spine: the keys campaign_write_manifest itself defines, and the
# only ones a caller may not redefine. Computed from the literal below rather
# than from the manifest on disk -- an earlier invocation's own extras are in
# there too, and reserving *those* refuses the very caller that wrote them.
manifest = dict(existing)
spine = {
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
    "mrt_files": sorted(set(existing.get("mrt_files", []))),
    "mrt_override": mrt_override or existing.get("mrt_override"),
}
manifest.update(spine)

mrt_files = set(manifest["mrt_files"])
for config_path in configs:
    with open(config_path, "r", encoding="utf-8") as config_file:
        for line in config_file:
            stripped = line.strip()
            if stripped.startswith("mrt_file:"):
                mrt_files.add(stripped.split(":", 1)[1].strip())
manifest["mrt_files"] = sorted(mrt_files)

# A caller may not quietly redefine one of the spine keys: a
# MANIFEST_EXTRA_JSON carrying its own "workdir" would silently undo the
# refusal a few lines up, which is the one guard standing between a resumed
# block and a manifest that disagrees with where its logs went. Refused by
# name, so the caller is told which key rather than finding out from a
# manifest that reads as though it were written by this script.
#
# Tested against the spine and never against the merged document: the block
# runner records its facts under "blocks", pre-merging what earlier blocks
# recorded, so a check against `manifest` refused every invocation after the
# first -- under `set -e`, aborting the second block of a run ID before its
# preflight.
reserved = sorted(set(spine) & set(extra))
if reserved:
    sys.stderr.write(
        "MANIFEST_EXTRA_JSON may not redefine manifest keys: {0}.\n".format(
            ", ".join(reserved)))
    raise SystemExit(1)
manifest.update(extra)

tmp_path = manifest_path + ".tmp"
with open(tmp_path, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, sort_keys=True)
    f.write("\n")
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp_path, manifest_path)
PY
}
