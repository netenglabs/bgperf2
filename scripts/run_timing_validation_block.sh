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
  --with-exclusions     Accept a block whose evidence rejected one or more
                        rows, recording them in the COMPLETE marker as durable
                        exclusions. Requires --note. (accept only)
  --force               Re-measure a block, discarding its previous results,
                        artifacts, markers and batch progress
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
WITH_EXCLUSIONS=0
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
    --with-exclusions) WITH_EXCLUSIONS=1; shift ;;
    --allow-root-workdir) ALLOW_ROOT_WORKDIR=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

# `--with-exclusions` and `--note` mean something only to `accept`, and are
# refused elsewhere rather than ignored -- the same rule the flag itself follows
# on a clean block. It matters more here than it reads: the `next` refusal
# message prints an `accept N --with-exclusions --note` line for the operator to
# copy, so leaving the action as `next` is the natural slip, and ignoring the
# flags would launch a multi-hour benchmark instead of refusing.
if [[ "$ACTION" != "accept" ]]; then
  accept_only=()
  [[ $WITH_EXCLUSIONS -eq 1 ]] && accept_only+=("--with-exclusions")
  [[ -n "$NOTE" ]] && accept_only+=("--note")
  if [[ ${#accept_only[@]} -gt 0 ]]; then
    echo "${accept_only[*]} applies to \`accept\`, not to \`$ACTION\`" >&2
    echo "did you mean: scripts/run_timing_validation_block.sh accept N ${accept_only[*]} ..." >&2
    exit 1
  fi
elif [[ $FORCE -eq 1 ]]; then
  # `accept` re-measures nothing, so --force there means nothing -- and a
  # plausible slip when trying to re-accept a block. Refused on the same rule
  # the flags above follow: a flag that quietly does nothing is read next time
  # as one that did something.
  echo "--force re-measures a block and does not apply to \`accept\`" >&2
  echo "to replace an acceptance, re-run the block: block-N --force" >&2
  exit 1
fi

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

# What a block's evidence rejected, read from the verdicts themselves rather
# than from a count of failed checker invocations.
#
# Blocks 2-7 make exactly one `check_evidence` call covering all 14 runs, so a
# count of failed *calls* is 1 whether one row was rejected or fourteen -- and
# `check_timing_evidence.py` also exits non-zero on a shortfall, so a block
# that produced 9 artifacts for 14 configurations reached `accept` under the
# identical wording. Those are the two things this campaign is required to keep
# apart everywhere else: a row that failed is a result to investigate, a run
# that never happened is unfinished work, and only the first can be an
# exclusion. So both are named, separately, in the marker that outlives the
# session.
#
# Prints one `key: text` line per fact, or nothing when the block has no
# evidence directory (a block from an older build, or one that never got that
# far).
block_exclusion_report() {
  local dir="$1"
  [[ -d "$dir/evidence" ]] || return 0
  EVIDENCE_DIR="$dir/evidence" "$PYTHON_BIN" - <<'PYEV'
import glob
import json
import os

rejected = []
missing = []
for path in sorted(glob.glob(os.path.join(os.environ["EVIDENCE_DIR"], "*.json"))):
    label = os.path.basename(path)[: -len(".json")]
    try:
        with open(path, "r", encoding="utf-8") as f:
            document = json.load(f)
    except (OSError, ValueError) as exc:
        # An unreadable verdict is not an absent one. Naming it keeps a block
        # from being accepted as one with nothing to exclude.
        missing.append("{0}: verdict unreadable ({1})".format(label, exc))
        continue
    for run in document.get("runs") or []:
        verdict = run.get("verdict")
        if verdict == "qualified":
            continue
        name = run.get("run") or run.get("artifact") or "unnamed"
        # An `unreadable` verdict means the checker could not parse that run's
        # `.events.json` at all, so its `checks` are empty and nothing was
        # actually judged. That is not a row that failed a rule -- it is a row
        # with no evidence, and "explicit durable exclusions *with evidence*"
        # cannot be satisfied by one. It belongs with the shortfalls, which
        # make the block unfinished rather than excludable.
        if verdict == "unreadable":
            missing.append("{0}: {1} (evidence unreadable)".format(label, name))
        else:
            rejected.append("{0}: {1} ({2})".format(
                label, name, verdict or "no verdict"))
    shortfall = document.get("shortfall")
    if shortfall:
        missing.append("{0}: {1}".format(label, shortfall))

for line in rejected:
    print("excluded_row: " + line)
for line in missing:
    print("missing_runs: " + line)
if rejected or missing:
    print("exclusion_counts: {0} rejected row(s), {1} shortfall(s)".format(
        len(rejected), len(missing)))
PYEV
}

# What a block's evidence entitles it to, decided on the parsed verdicts rather
# than on the wording of a message.
#
# Reporting the two apart is not the same as *treating* them apart, and the
# first version of this got exactly that wrong: `--with-exclusions` proceeded on
# any non-zero failure count, so a block whose only fault was
# "9 runs found, 14 expected" was stamped COMPLETE and `next` advanced past five
# configurations nobody measured. A guard is code and gets the rule as wrong as
# the code it guards.
#
# Sets:
#   BLOCK_EXCLUSION_CLASS   clean       every check qualified
#                           excludable  rejected row(s), and every configured
#                                       run produced a row
#                           unfinished  at least one run never happened; not an
#                                       exclusion at any count of rejected rows
#                                       beside it, because the block is not done
#                           no-evidence the checks failed and no verdict can be
#                                       read -- the checker itself died, or the
#                                       directory is gone. "Explicit durable
#                                       exclusions *with evidence*" cannot be
#                                       satisfied by a record with none.
#   BLOCK_EXCLUSION_DETAIL  the per-row lines, empty when there are none
classify_block_evidence() {
  local dir="$1"
  BLOCK_EXCLUSION_DETAIL=""
  BLOCK_EXCLUSION_CLASS="clean"
  grep -q '^evidence: .* check(s) failed$' "$dir/RAN" 2>/dev/null || return 0
  BLOCK_EXCLUSION_DETAIL="$(block_exclusion_report "$dir")"
  if grep -q '^missing_runs: ' <<<"$BLOCK_EXCLUSION_DETAIL"; then
    BLOCK_EXCLUSION_CLASS="unfinished"
  elif grep -q '^excluded_row: ' <<<"$BLOCK_EXCLUSION_DETAIL"; then
    BLOCK_EXCLUSION_CLASS="excludable"
  else
    BLOCK_EXCLUSION_CLASS="no-evidence"
  fi
}

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
  # A block whose own evidence rejected a row is exactly the plan's "14
  # reviewed rows *or* explicit durable exclusions with evidence", and the
  # second half of that has to be written down or it is not durable. So the
  # rejection does not block acceptance -- it demands that the acceptance say
  # so, in the marker, with a reason. Silence here would let a block with a
  # failed OpenBGPD row be accepted by the same keystroke as a clean one, and
  # nothing downstream reads the evidence directory.
  # Re-read the verdicts rather than trusting the marker's copy of them: a block
  # from a build before this reported anything but a count has no detail in RAN,
  # and its evidence directory is still on disk.
  classify_block_evidence "$dir"
  EXCLUSION_SUMMARY=""
  EXCLUSION_DETAIL="$BLOCK_EXCLUSION_DETAIL"
  case "$BLOCK_EXCLUSION_CLASS" in
    clean)
      if [[ $WITH_EXCLUSIONS -eq 1 ]]; then
        # Refused rather than ignored: a flag that quietly does nothing is read
        # next time as one that did something.
        echo "block-$index has no rejected rows; --with-exclusions does not apply" >&2
        exit 1
      fi
      ;;
    unfinished)
      # Never acceptable, with or without the flag. A configuration that
      # produced no row is work still to do, and stamping COMPLETE here makes
      # `next` advance past runs nobody measured -- the one thing the two
      # markers exist to prevent.
      cat >&2 <<MSG
block-$index is unfinished: some configurations produced no row at all.

$EXCLUSION_DETAIL

A "missing_runs" line is not an exclusion. Re-measure:
  scripts/run_timing_validation_block.sh block-$index --force
MSG
      exit 1
      ;;
    no-evidence)
      # The checks failed and no verdict can be read -- the checker died, or the
      # directory is gone. Accepting here would write a durable exclusion record
      # naming an evidence path that holds nothing, which is what "explicit
      # durable exclusions *with evidence*" exists to refuse.
      cat >&2 <<MSG
block-$index has failing checks and no readable verdicts under $dir/evidence/.

There is nothing here to exclude a row on. Find out why the checker produced no
verdict, then re-measure:
  scripts/run_timing_validation_block.sh block-$index --force
MSG
      exit 1
      ;;
    excludable)
      if [[ $WITH_EXCLUSIONS -eq 0 ]]; then
        cat >&2 <<MSG
block-$index ran with rejected rows.

$EXCLUSION_DETAIL

Every configured run produced a row, so these may be recorded as durable
exclusions:
  scripts/run_timing_validation_block.sh accept $index --with-exclusions --note "why"
MSG
        exit 1
      fi
      if [[ -z "$NOTE" ]]; then
        echo "--with-exclusions requires --note: an exclusion with no reason is" >&2
        echo "a row dropped, not a row excluded" >&2
        exit 1
      fi
      EXCLUSION_SUMMARY="$(sed -n 's/^exclusion_counts: //p' <<<"$EXCLUSION_DETAIL")"
      ;;
  esac
  {
    echo "block: ${BLOCK_KEYS[$index]}"
    echo "title: ${BLOCK_TITLES[$index]}"
    echo "accepted_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "accepted_by: ${USER:-unknown}"
    echo "revision: $(git -C . rev-parse HEAD)"
    if [[ -n "$EXCLUSION_SUMMARY" ]]; then
      echo "accepted_with_exclusions: $EXCLUSION_SUMMARY"
      echo "$EXCLUSION_DETAIL"
      echo "exclusion_evidence: $dir/evidence/"
    fi
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
    # A block reaches awaiting-review with rejected rows too, and `accept`
    # refuses the bare form for exactly those. This message is what an operator
    # returning in a later session sees -- the end-of-run one is long gone, which
    # is the whole reason the markers are durable -- so it has to print the
    # command that will work on *this* block rather than the one that works on a
    # clean one.
    # Derived from the same verdict read the gate uses, never from the failure
    # count alone: a block whose fault is a shortfall must not be pointed at an
    # `accept` that would mark unmeasured configurations complete -- and that is
    # what the count-only version printed.
    classify_block_evidence "$RUN_ROOT/${BLOCK_KEYS[$BLOCK_INDEX]}"
    case "$BLOCK_EXCLUSION_CLASS" in
      clean)      next_step="accept $BLOCK_INDEX --note \"...\"" ;;
      excludable) next_step="accept $BLOCK_INDEX --with-exclusions --note \"...\"" ;;
      *)          next_step="block-$BLOCK_INDEX --force   # unfinished or unreadable; re-measure" ;;
    esac
    cat >&2 <<MSG
block-$BLOCK_INDEX (${BLOCK_TITLES[$BLOCK_INDEX]}) has already run and is waiting to be reviewed.

$(sed -n 's/^evidence: /evidence: /p' "$RUN_ROOT/${BLOCK_KEYS[$BLOCK_INDEX]}/RAN" 2>/dev/null)
${BLOCK_EXCLUSION_DETAIL:+
$BLOCK_EXCLUSION_DETAIL
}
Read its evidence under $RUN_ROOT/${BLOCK_KEYS[$BLOCK_INDEX]}, then:
  scripts/run_timing_validation_block.sh $next_step

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

# A metadata file is written per *block* when its content exists nowhere else,
# and per run root when the manifest already carries the same fact under
# `blocks.<key>`. Five are keyed:
#
#   preflight, verify, mrt-validation  no manifest equivalent at all. `verify`
#       in particular is the only record that no daemon binary in the matrix
#       carried gcov instrumentation, the defect that made every FRR result
#       incomparable for years.
#   free-h, df-h                       `campaign_host_facts.py` records
#       `memory_total_kb` and `swap_total_kb` -- *totals* -- and nothing about
#       disk. Free memory, used swap and free space are precisely the figures
#       the 64 GB Safety Contract asks to preflight "before each ... block" and
#       to stop a block over ("swap growth"), and growth is a comparison
#       against the previous block. Unkeyed there was nothing left to compare
#       against: Block 1 had already overwritten Block 0's.
#
# `doctor.txt`, `images.txt`, `uname-a.txt` and the two git files may be
# overwritten, because the manifest merges the revision, the kernel and every
# image ID per block and those survive there.
#
# Unkeyed, Block 2 would have destroyed Block 0's -- an accepted block whose
# plan entry cites them -- and a --force re-run would have left the old one
# beside the new, describing a run that no longer exists.
#
# Keying per block is not enough on its own, because a block is entered once
# per *attempt* and a reclaimed spot host makes several attempts ordinary. The
# manifest entry is merged rather than replaced (see
# `campaign_merge_block_facts.py`), so a resumed block still names the host
# that measured its earlier rows. The two keyed pairs are not: `free-h` and
# `df-h` are overwritten by the resume and describe the machine that finished
# the block rather than the one that started it. That is a smaller loss --
# they are a preflight of the attempt about to run, which is what the Safety
# Contract asks them for -- but "growth against the previous block" is
# measured from a file the previous *attempt* may have written, so read them
# against the manifest's per-attempt host before concluding anything moved.
capture_metadata() {
  local configs=("$@")
  local config_list
  config_list="$(printf '%s\n' "${configs[@]}")"

  git -C . rev-parse HEAD > "$METADATA_DIR/git-rev-parse-head.txt"
  git -C . status --short > "$METADATA_DIR/git-status-short.txt"
  uname -a > "$METADATA_DIR/uname-a.txt"
  free -h > "$METADATA_DIR/free-h-$BLOCK_KEY.txt"
  {
    df -h "$WORKDIR"
    df -h "$RUN_ROOT"
  } > "$METADATA_DIR/df-h-$BLOCK_KEY.txt"
  "${BGPERF_CMD[@]}" doctor > "$METADATA_DIR/doctor.txt" 2>&1 || true
  "${BGPERF_CMD[@]}" images > "$METADATA_DIR/images.txt" 2>&1 || true

  local facts
  facts="$("$PYTHON_BIN" scripts/campaign_host_facts.py "$MRT_INPUT")"
  # Under one key so the block's facts cannot collide with the manifest's own
  # spine, and per block because images are rebuilt and hosts are resized
  # between them: one shared record would describe whichever block wrote last.
  local entry
  entry="$(FACTS="$facts" BLOCK_INDEX="$BLOCK_INDEX" \
    BLOCK_TITLE="${BLOCK_TITLES[$BLOCK_INDEX]}" "$PYTHON_BIN" - <<'PY'
import json
import os
facts = json.loads(os.environ["FACTS"])
facts["block_index"] = int(os.environ["BLOCK_INDEX"])
facts["block_title"] = os.environ["BLOCK_TITLE"]
print(json.dumps(facts))
PY
)"
  # A manifest already carrying another block's facts must keep them -- the
  # merge is per run ID and "blocks" is one key -- and a block re-entered by a
  # resume must keep the facts of the entry it supersedes, which is what
  # `campaign_merge_block_facts.py` is for.
  #
  # It always keeps here, `--force` included. This runs before preflight,
  # `verify` and the MRT validation, every one of which can end the block, so
  # a forced run that never reached a container would otherwise have thrown
  # away the history of rows that are all still on disk with their markers --
  # attributing them to a host that measured none of them, which is the
  # provenance loss this merge exists to prevent. Forgetting belongs where the
  # results are actually deleted, and `run_batch` prunes there.
  local extra
  extra="$(printf '%s' "$entry" | "$PYTHON_BIN" \
    scripts/campaign_merge_block_facts.py \
    --manifest "$METADATA_DIR/manifest.json" \
    --block-key "$BLOCK_KEY" --results-dir "$BLOCK_DIR" \
    --keeps-previous-rows)"

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
    # And the verdicts, for the same reason. `block_exclusion_report` globs
    # every evidence/*.json, and the labels are hardcoded per block -- so if a
    # block's set of cases ever changes, the previous measurement's verdict
    # file survives the forced re-run and is read back as a rejected row of the
    # new one. `next` would then point at --with-exclusions and `accept` would
    # write a durable exclusion naming a run that no longer exists.
    rm -rf "$BLOCK_DIR/evidence"
  fi
}

# Anything after the output directory is a scripts/calibration_case.sh
# constraint (`--role tester --rate 4mbit`), which starves one role from
# outside bgperf2 for the duration of the run. It *replaces* the interpreter
# invocation rather than prefixing it: that script takes bgperf2's arguments
# after `--` and runs bgperf2 itself, so putting it in front of
# "$PYTHON_BIN bgperf2.py" would hand bgperf2 its own command line as a
# positional argument.
#
# It exits non-zero when any container of the run went unconstrained, and that
# is deliberately fatal here rather than counted like an evidence failure: a
# case that was not controlled says nothing about the role it names, and
# stamping the block RAN would offer it for review as though it did. Each
# case's unconstrained companion runs first, so a constraint that fails to
# bind still leaves the reference it would have been read against on disk.
run_batch() {
  local key="$1"
  local out_dir="$2"
  shift 2
  local -a launch=("${BGPERF_CMD[@]}")
  if [[ $# -gt 0 ]]; then
    launch=(scripts/calibration_case.sh "$@" --)
  fi
  local rendered="$RENDERED_CONFIG_DIR/$key.yaml"
  # A forced run replaces this output, and the previous run's artifacts have to
  # go with it. `--force` drops `--resume`, which makes `batch()` unlink the
  # progress file, but nothing removed the `.events.json` / `.versions.json`
  # left behind -- so a forced re-run under an edited matrix left one artifact
  # per dropped target beside the new ones, and `check_evidence`, which counts
  # the artifacts it finds, reported a permanent shortfall against a block that
  # had measured exactly what it was asked to. Cleared here rather than in
  # `retract_forced_markers` because this is the one place that knows which
  # directory is about to be rewritten, and only the directory being rewritten
  # may be cleared.
  if [[ $FORCE -eq 1 && -d "$out_dir" ]]; then
    # Worked out and checked *before* the delete, not after: a guard that runs
    # afterwards cannot stop the thing it guards against, and the state it was
    # written to prevent -- results gone, manifest still naming them -- is
    # exactly what it would leave behind.
    local prune_under="${out_dir%/}"
    if [[ "$prune_under" == "${BLOCK_DIR%/}" ]]; then
      prune_under=.
    elif [[ "$prune_under" == "${BLOCK_DIR%/}"/* ]]; then
      prune_under="${prune_under#"${BLOCK_DIR%/}"/}"
    else
      echo "run_batch: $out_dir is not under $BLOCK_DIR, so the manifest" >&2
      echo "cannot say which rows a forced re-run discarded; refusing" >&2
      exit 1
    fi
    echo "force: discarding previous results under $out_dir"
    rm -rf "${out_dir:?}"
    # The manifest stops naming those rows at the moment they stop existing,
    # not at the moment the block was entered -- see capture_metadata. Scoped
    # to the directory just removed, because a block is not always one batch:
    # Block 1 makes four of these calls, and forgetting everything on the
    # first would drop the host of three directories still on disk.
    #
    # Derived in the shell rather than with `realpath`, whose failure inside a
    # command substitution is an empty argument that `set -e` does not catch --
    # and an empty --prune-under would once have meant "forget every carried
    # row".
    "$PYTHON_BIN" scripts/campaign_merge_block_facts.py \
      --manifest "$METADATA_DIR/manifest.json" --block-key "$BLOCK_KEY" \
      --prune-under "$prune_under"
  fi
  mkdir -p "$out_dir"
  echo "Running $key -> $out_dir"
  # --resume is what makes an interrupted block resumable, and it is exactly
  # wrong under --force: `batch --resume` records every completed cell in
  # <test>.progress.json, so a forced re-run would skip all of them, exit 0
  # having measured nothing, and the block would then stamp the *old*
  # artifacts with the current revision and ask an operator to accept rows
  # nobody re-measured. The sibling runner drops it for the same reason.
  #
  # **A constrained case is never resumed**, for a third reason. The progress
  # file records that a cell completed and records nothing about whether the
  # constraint bound; the guard that decides that runs in the watcher, which
  # cannot observe a cell it did not launch. So resuming one would accept a
  # cell as controlled on the strength of a marker that says nothing about
  # control -- and a case whose constraint failed *after* the batch wrote its
  # progress would be replayed as a skipped cell, leaving the watcher to
  # report "no container of this run was seen at all", which reads as a naming
  # bug rather than as the constraint failure it is. Re-measuring costs the
  # case's own minute.
  local resume_args=(--resume)
  if [[ $FORCE -eq 1 || $# -gt 0 ]]; then
    resume_args=()
  fi
  local status=0
  "${launch[@]}" -d "$WORKDIR" batch -c "$rendered" \
    --results-dir "$out_dir" "${resume_args[@]}" \
    > "$LOG_DIR/$key.stdout.log" 2> "$LOG_DIR/$key.stderr.log" || status=$?

  # bgperf2 is never told about the constraint -- provenance never guesses,
  # and a manifest may not claim something the tool did not do -- so the
  # harness's own log is the only record that this case was controlled. Keep
  # it beside the results it qualifies, not only under metadata/logs, and
  # keep it on the failing path too: a case that went unconstrained is exactly
  # the one whose record matters.
  if [[ $# -gt 0 ]]; then
    cp "$LOG_DIR/$key.stderr.log" "$out_dir/case.log"
  fi

  if [[ $status -ne 0 ]]; then
    # Everything this run had to say is in a redirected log, so failing on the
    # bare exit status under `set -e` would abort the block with nothing on
    # the terminal -- including the one message the whole design turns on,
    # "FAILED: tester containers of this run went unconstrained by".
    echo "$key failed (exit $status); see $LOG_DIR/$key.stderr.log" >&2
    tail -20 "$LOG_DIR/$key.stderr.log" >&2
    return "$status"
  fi
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
  shift 3
  # Anything further is passed to the checker: a calibration case adds what it
  # was built to produce (--expect-limiting, --expect-egress-mbit).
  local status=0
  mkdir -p "$BLOCK_DIR/evidence"
  "$PYTHON_BIN" scripts/check_timing_evidence.py "$out_dir" \
    --expect "$expect" --json "$BLOCK_DIR/evidence/$label.json" "$@" \
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
      | tee "$METADATA_DIR/preflight-$BLOCK_KEY.txt"

    # `verify` is the only check that puts a real container in front of each
    # parser, and it is where the version-reporting bugs have been. A campaign
    # whose provenance columns are wrong is a campaign of unattributable rows,
    # so this is fatal rather than captured-and-ignored.
    echo "Verifying built images"
    "${BGPERF_CMD[@]}" verify > "$METADATA_DIR/verify-$BLOCK_KEY.txt" 2>&1 || {
      echo "verify failed; see $METADATA_DIR/verify-$BLOCK_KEY.txt" >&2
      tail -20 "$METADATA_DIR/verify-$BLOCK_KEY.txt" >&2
      exit 1
    }
    tail -5 "$METADATA_DIR/verify-$BLOCK_KEY.txt"

    # The pinned RIB, read by bgpdump2 itself. The file's size is in the
    # manifest; this is the only thing that says the injectors can parse it.
    echo "Validating pinned MRT: $MRT_INPUT"
    scripts/prepare_mrt.sh "$MRT_INPUT" > "$METADATA_DIR/mrt-validation-$BLOCK_KEY.txt" 2>&1 || {
      echo "MRT validation failed; see $METADATA_DIR/mrt-validation-$BLOCK_KEY.txt" >&2
      tail -20 "$METADATA_DIR/mrt-validation-$BLOCK_KEY.txt" >&2
      exit 1
    }
    tail -4 "$METADATA_DIR/mrt-validation-$BLOCK_KEY.txt"

    retract_forced_markers
    run_batch "block0-smoke-synth" "$BLOCK_DIR/smoke-synth"
    run_batch "block0-smoke-mrt" "$BLOCK_DIR/smoke-mrt"

    check_evidence "$BLOCK_DIR/smoke-synth" 1 "smoke-synth"
    check_evidence "$BLOCK_DIR/smoke-mrt" 1 "smoke-mrt"
    ;;
  1)
    # Generator calibration: four runs from two configs, each config run twice
    # -- once unconstrained, once with one role starved from outside bgperf2 by
    # scripts/calibration_case.sh. The plan asks for a controlled slow tester
    # and a controlled target/observer tail; the two unconstrained companions
    # are what makes each of those a *controlled* case rather than an observed
    # one, and one of them is also the block's ambiguous case.
    #
    # The pairs are qualified on different evidence, and deliberately so:
    #
    #   tail pair    separates on the verdict. Byte-identical inputs give
    #                `unresolved` unconstrained and `target_or_monitor` with
    #                the monitor at 0.15 CPU.
    #   tester pair  may not separate on the verdict at all, so it is not
    #                qualified on one. 2 x 500,000 unconstrained was attributed
    #                to `tester` in Phase 6, i.e. to the very component this
    #                case starves -- so a slow-tester case cleared by its
    #                verdict would also have been cleared by a constraint that
    #                bound nothing, which has happened here
    #                (results/2026/phase6-calibration/interface-probe/, where
    #                `tc` succeeded on a device the BGP session did not use).
    #                What qualifies it is the imposed 4 mbit cap being
    #                recovered from each injector's own `octets_on_wire` and
    #                `reported_injection_s`. The companion supplies the
    #                unconstrained rate that is read against, which is why it
    #                is run even though its own verdict is pinned to nothing.
    #
    # Each companion runs before its constrained case, so a constraint that
    # fails to bind -- which is fatal -- still leaves the reference it would
    # have been read against on disk.
    TAIL_CONFIG="benchmarks/2026-calibration-block1-tail.yaml"
    TESTER_CONFIG="benchmarks/2026-calibration-block1-tester.yaml"
    # One source config under two snapshot keys, so the two runs of a pair are
    # recorded as the identical input they are.
    campaign_render_config "block1-tail-baseline" "$TAIL_CONFIG" \
      "$RENDERED_CONFIG_DIR/block1-tail-baseline.yaml"
    campaign_render_config "block1-observer-tail" "$TAIL_CONFIG" \
      "$RENDERED_CONFIG_DIR/block1-observer-tail.yaml"
    campaign_render_config "block1-tester-baseline" "$TESTER_CONFIG" \
      "$RENDERED_CONFIG_DIR/block1-tester-baseline.yaml"
    campaign_render_config "block1-slow-tester" "$TESTER_CONFIG" \
      "$RENDERED_CONFIG_DIR/block1-slow-tester.yaml"
    capture_metadata "$RENDERED_CONFIG_DIR/block1-tail-baseline.yaml" \
                     "$RENDERED_CONFIG_DIR/block1-observer-tail.yaml" \
                     "$RENDERED_CONFIG_DIR/block1-tester-baseline.yaml" \
                     "$RENDERED_CONFIG_DIR/block1-slow-tester.yaml"

    retract_forced_markers

    run_batch "block1-tail-baseline" "$BLOCK_DIR/tail-baseline"
    # `unresolved` and `inconclusive` are kept apart everywhere else -- one is
    # a measurement that forbids attribution, the other a measurement never
    # made -- and both are correct for a run with nothing constrained. What
    # this rejects is a component named where no cause was imposed.
    check_evidence "$BLOCK_DIR/tail-baseline" 1 "tail-baseline" \
      --expect-limiting unresolved,inconclusive

    run_batch "block1-observer-tail" "$BLOCK_DIR/observer-tail" \
      --role monitor --cpus 0.15
    check_evidence "$BLOCK_DIR/observer-tail" 1 "observer-tail" \
      --expect-limiting target_or_monitor

    # No expected component for the tester companion: it is the reference rate,
    # not a control on the verdict, and pinning one would add a failure mode
    # the block's exit criterion does not ask about. Its rate is published as a
    # note either way.
    run_batch "block1-tester-baseline" "$BLOCK_DIR/tester-baseline"
    check_evidence "$BLOCK_DIR/tester-baseline" 1 "tester-baseline"

    run_batch "block1-slow-tester" "$BLOCK_DIR/slow-tester" \
      --role tester --rate 4mbit
    check_evidence "$BLOCK_DIR/slow-tester" 1 "slow-tester" \
      --expect-limiting tester --expect-egress-mbit 4
    ;;
  2)
    # Repetition 1 of the high-load synthetic workload: the plan's 14 target
    # configurations at 50 peers x 100,000 prefixes per peer, one pass, in the
    # order seed 20262 fixes. Blocks 3 and 4 are the other two repetitions and
    # differ only in their seed; the three passes are read together in Block 9.
    #
    # `verify` runs here as well as in Block 0, and it is the one check worth
    # repeating per benchmark block. Blocks are days apart, `prepare` skips a
    # tag that already exists, and an FRR image rebuilt with --enable-gcov in
    # between would benchmark an instrumented binary against everyone else's
    # optimized one -- a distortion that lands in exactly the CPU and memory
    # columns this block publishes, with nothing looking wrong. Five of the 14
    # configurations are FRR. It costs about twenty seconds against a block of
    # roughly ninety minutes, and it is fatal for the reason it is fatal in
    # Block 0: a campaign whose provenance is wrong is a campaign of
    # unattributable rows.
    SYNTH_CONFIG="benchmarks/2026-timing-synth-rep1.yaml"
    campaign_render_config "block2-synthetic-rep1" "$SYNTH_CONFIG" \
      "$RENDERED_CONFIG_DIR/block2-synthetic-rep1.yaml"
    capture_metadata "$RENDERED_CONFIG_DIR/block2-synthetic-rep1.yaml"

    scripts/preflight_2026_suite.sh --workdir "$WORKDIR" --run-root "$RUN_ROOT" \
      --config "$RENDERED_CONFIG_DIR/block2-synthetic-rep1.yaml" \
      | tee "$METADATA_DIR/preflight-$BLOCK_KEY.txt"

    echo "Verifying built images"
    "${BGPERF_CMD[@]}" verify > "$METADATA_DIR/verify-$BLOCK_KEY.txt" 2>&1 || {
      echo "verify failed; see $METADATA_DIR/verify-$BLOCK_KEY.txt" >&2
      tail -20 "$METADATA_DIR/verify-$BLOCK_KEY.txt" >&2
      exit 1
    }
    tail -5 "$METADATA_DIR/verify-$BLOCK_KEY.txt"

    retract_forced_markers
    run_batch "block2-synthetic-rep1" "$BLOCK_DIR/synthetic"

    # 14 runs, every one of them qualified. No --expect-limiting: nothing here
    # is a controlled case, so which component limits a given target at this
    # size is the measurement rather than the setup. What the checker still
    # requires is that each row *has* a verdict, assigned or explicitly left
    # unresolved.
    check_evidence "$BLOCK_DIR/synthetic" 14 "synthetic"
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

# RAN records that the block's mechanical work finished, and it is written
# whether or not the evidence qualified. It used to be written only on the
# passing path, and that made a rejected block unrecoverable in two ways at
# once.
#
# `accept` refuses a block with no RAN, so the only route past a single
# rejected row was `--force` -- a full re-measure that reproduces the same
# rejection. And `next` would not even get there: with no RAN but a directory
# on disk, `block_state` says `started`, so `next` selects the block again and
# `run_batch` runs it with `--resume`, which skips every cell already in the
# progress file *including the failed ones* -- `batch()` records
# `completed[cell_id] = bench(a)` for a FAILED run exactly as for a converged
# one. The block re-ran, measured nothing, exited 0, and failed the identical
# check. The cell that most needed re-measuring was the one resume would never
# re-run.
#
# So the marker states the fact it is named for -- the work ran -- and carries
# the verdict beside it. What the verdict still controls is the exit status
# (loud, so nothing looks green) and what `accept` demands: a block whose
# evidence rejected a row may only be accepted with --with-exclusions and a
# note, which is the plan's "explicit durable exclusions with evidence"
# written down where it cannot be forgotten.
{
  echo "block: $BLOCK_KEY"
  echo "title: ${BLOCK_TITLES[$BLOCK_INDEX]}"
  echo "ran_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "revision: $(git -C . rev-parse HEAD)"
  echo "workdir: $WORKDIR"
  if [[ $EVIDENCE_FAILURES -gt 0 ]]; then
    echo "evidence: $EVIDENCE_FAILURES check(s) failed"
    # Which rows, and which runs never happened -- the count of failed checker
    # calls is 1 for a block of 14 whether one row was rejected or all of them.
    block_exclusion_report "$BLOCK_DIR"
  else
    echo "evidence: all checks qualified"
  fi
} > "$BLOCK_DIR/RAN"

if [[ $EVIDENCE_FAILURES -gt 0 ]]; then
  cat >&2 <<MSG

block-$BLOCK_INDEX did not meet its exit criterion: $EVIDENCE_FAILURES evidence check(s) failed.

The results and the verdicts are under $BLOCK_DIR. Read
$BLOCK_DIR/evidence/ and decide whether this is a run to
investigate or a rule to argue with.

The block is recorded as having run, so nothing here has to be re-measured to
be looked at.

$(classify_block_evidence "$BLOCK_DIR"; case "$BLOCK_EXCLUSION_CLASS" in
  excludable) echo "Every configured run produced a row. When the rejected rows are a durable
exclusion rather than a fault to fix:
  scripts/run_timing_validation_block.sh accept $BLOCK_INDEX --with-exclusions --note \"...\"" ;;
  unfinished) echo "Some configurations produced no row at all, so this block is unfinished
rather than excludable. Re-measure:
  scripts/run_timing_validation_block.sh block-$BLOCK_INDEX --force" ;;
  *)          echo "No per-row verdict could be read. Find out why, then re-measure:
  scripts/run_timing_validation_block.sh block-$BLOCK_INDEX --force" ;;
esac)

Note that a plain re-run resumes past every cell the progress file already
holds, failed ones included; only --force re-measures.
MSG
  exit 1
fi

cat <<MSG

block-$BLOCK_INDEX ran. It is NOT complete until it is reviewed:

  read $BLOCK_DIR/evidence/
  then: scripts/run_timing_validation_block.sh accept $BLOCK_INDEX --note "..."
MSG
