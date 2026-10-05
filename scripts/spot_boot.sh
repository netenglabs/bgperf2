#!/usr/bin/env bash
set -uo pipefail

# Keep the 2026 daemon comparison going across spot reclaims, unattended.
#
# Started at every launch by /data/on-launch.sh, which ec2m runs as part of its
# user-data (the `[remote] launch` hook), as ubuntu under systemd-run so
# cloud-init is not held. Everything it needs is on /data, the one volume a
# reclaim keeps: the repo, the work directory, the queue, the alert channel
# and the Claude login under the bind-mounted home.
#
# The loop, each step of which is idempotent so a reclaim at any point is
# resumed by the next launch:
#   1. Wrong host (not the m7a.8xlarge): alert, stay up, run nothing.
#   2. Take the first config in the queue and run it to completion with
#      run_comparison_step.sh --wait, which resumes it when it has run before.
#      A spot notice stops it at a cell boundary (exit 143); that is the end
#      of this launch, not a failure.
#   3. Start one headless Claude session to record the finished step
#      (scripts/unattended_comparison_prompt.md). It edits the queue itself:
#      it removes the step it recorded, and adds any re-run the operator's
#      rules call for. It reports RECORDED, GATE or FAILED in a status file.
#   4. RECORDED: back to 2. GATE: alert with what the operator must decide,
#      and stop. Anything else: alert and stop.
#
# A finished batch whose recording never happened (the reclaim landed during
# the session) is simply run again: `batch --resume` over a complete matrix
# skips every cell, and the session records it.
#
# Headless sessions commit to $BRANCH, never master, as CLAUDE.md requires of
# unattended work. The operator merges it. With the checkout anywhere else,
# or dirty, benchmarks still run and recording waits for the operator.

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
WORKDIR=/data/bgperf-work
# The only directory a headless session may write outside the repo. Nothing
# in it is ever executed or sourced: the env file, the lock, the logs and the
# bench directory all stay out of the session's reach.
SESSION_DIR="$WORKDIR/unattended"
QUEUE="$SESSION_DIR/comparison-queue"
STATUS="$SESSION_DIR/status"
ENV_FILE="$WORKDIR/unattended.env"
BRANCH=unattended/comparison
WORKER_TIMEOUT="${WORKER_TIMEOUT:-7200}"
PROMPT_FILE="$SCRIPT_DIR/unattended_comparison_prompt.md"

# systemd-run gives a bare environment; claude lives under the home on /data.
export HOME="${HOME:-/home/ubuntu}"
export PATH="$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

mkdir -p "$WORKDIR/logs"
LOG="$WORKDIR/logs/spot-boot-$(date -u +%Y%m%dT%H%M%S).log"
exec >>"$LOG" 2>&1
log() { echo "$(date -u +%H:%M:%S) $*"; }

# One driver per host. The lock dies with its holder, so a reclaimed
# instance leaves nothing to clear.
exec 9>"$WORKDIR/.spot-boot.lock"
if ! flock -n 9; then
  log "another spot_boot.sh holds the lock; exiting"
  exit 0
fi

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck source=/dev/null
  source "$ENV_FILE"
else
  log "no $ENV_FILE: alerts cannot be sent"
fi

alert() {
  log "ALERT: $1${2:+ -- $2}"
  "$SCRIPT_DIR/notify_gate.sh" "$1" "${2:-}" || log "the alert above was NOT delivered"
}

instance_type() {
  local token
  token="$(curl -s -m 2 -X PUT http://169.254.169.254/latest/api/token \
    -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')" || true
  curl -s -m 2 -H "X-aws-ec2-metadata-token: $token" \
    http://169.254.169.254/latest/meta-data/instance-type || echo unknown
}

# 200 means a notice is pending; anything else (404, no IMDS) means none.
spot_notice_pending() {
  local token code
  token="$(curl -s -m 2 -X PUT http://169.254.169.254/latest/api/token \
    -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')" || return 1
  code="$(curl -s -m 2 -o /dev/null -w '%{http_code}' \
    -H "X-aws-ec2-metadata-token: $token" \
    http://169.254.169.254/latest/meta-data/spot/instance-action)" || return 1
  [[ "$code" == 200 ]]
}

queue_head() {
  [[ -f "$QUEUE" ]] || return 0
  grep -v -e '^[[:space:]]*#' -e '^[[:space:]]*$' "$QUEUE" | head -1 | tr -d '[:space:]'
}

log "spot_boot.sh starting on $(instance_type), repo $REPO_ROOT, log $LOG"

mkdir -p "$SESSION_DIR"
# The queue's first home was the work directory itself, where a session could
# also reach the env file this script sources.
if [[ -f "$WORKDIR/comparison-queue" && ! -e "$QUEUE" ]]; then
  mv "$WORKDIR/comparison-queue" "$QUEUE" && log "moved the queue to $QUEUE"
fi
cd "$REPO_ROOT" || { alert "spot_boot: no repo at $REPO_ROOT"; exit 1; }

# Docker comes up during user-data; give it ten minutes.
for _ in $(seq 60); do
  docker info >/dev/null 2>&1 && break
  sleep 10
done
if ! docker info >/dev/null 2>&1; then
  alert "spot_boot: docker is not usable after 10 min on $(instance_type)" \
    "Nothing was run. Check the docker service and that ubuntu is in the docker group."
  exit 1
fi

if ! host_check="$(scripts/run_comparison_step.sh --check-host 2>&1)"; then
  alert "spot_boot: wrong host ($(instance_type)), nothing run" \
    "$host_check
The instance stays up. The queue resumes on the next launch that is an m7a.8xlarge."
  exit 0
fi

# Where headless sessions may commit.
HEADLESS=1
current="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
dirty="$(git -C "$REPO_ROOT" status --porcelain --untracked-files=no)"
if [[ -n "$dirty" ]]; then
  HEADLESS=0
  log "tracked files are modified, so no headless session will run:"
  log "$dirty"
elif [[ "$current" == master ]]; then
  if git -C "$REPO_ROOT" rev-parse --verify --quiet "refs/heads/$BRANCH" >/dev/null; then
    git -C "$REPO_ROOT" checkout "$BRANCH" || HEADLESS=0
  else
    git -C "$REPO_ROOT" checkout -b "$BRANCH" || HEADLESS=0
  fi
elif [[ "$current" != "$BRANCH" ]]; then
  HEADLESS=0
  log "checkout is on $current, not master or $BRANCH, so no headless session will run"
fi
# On every launch, not only the first: a fix merged to master between launches
# must reach the code the queue runs on. A branch with commits master lacks
# cannot fast-forward, and then it runs on code master has moved past -- said
# out loud, because the rows would carry a revision the operator thinks fixed.
if [[ "$HEADLESS" -eq 1 && "$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)" == "$BRANCH" ]] \
   && ! git -C "$REPO_ROOT" merge --ff-only master; then
  alert "spot_boot: $BRANCH has diverged from master" \
    "It holds commits master lacks, so it cannot take master's. The queue runs on $BRANCH as it is; merge it into master so the next launch runs current code."
fi

# What a headless session may do on this machine. Everything absent is denied
# in -p, where nobody can approve it -- provided nothing else allows it, which
# is why --setting-sources leaves out `local`: .claude/settings.local.json
# carries the operator's interactive allowances (a `python3 -c` among them),
# and arbitrary python reaches git push and docker without matching any deny. Same reasoning as
# unattended/measurement's scripts/unattended_driver.sh: prefix rules only,
# no `git -C` form (it would admit `git -C <dir> push`), and no `python -c`.
WORKER_ALLOWED_TOOLS=(
  Edit Write Read Glob Grep Skill TodoWrite
  "Bash(git add *)" "Bash(git commit *)" "Bash(git status *)" "Bash(git status)"
  "Bash(git diff *)" "Bash(git log *)" "Bash(git show *)"
  "Bash(bd show *)" "Bash(bd update *)" "Bash(bd close *)" "Bash(bd list *)"
  "Bash(bd ready *)"
  "Bash(venv/bin/python scripts/check_plan_beads.py *)"
  "Bash(venv/bin/python scripts/comparison_step_table.py *)"
  "Bash(lscpu)"
)
# Stated as well as omitted, so widening the allow list later cannot admit
# them: nothing unattended leaves this branch, touches docker, or starts a
# benchmark behind the queue's back.
WORKER_DENIED_TOOLS=(
  "Bash(git push *)" "Bash(git checkout *)" "Bash(git switch *)"
  "Bash(docker *)" "Bash(venv/bin/python bgperf2.py *)"
  "Bash(scripts/run_comparison_step.sh *)"
  "Bash(python3 *)" "Bash(python *)" "Bash(venv/bin/python -c *)"
  "Bash(bd dolt *)" "Bash(bd setup *)" "Bash(bd init *)" "Bash(bd hooks *)"
  # The worker writes the plan, its skill's records and benchmark configs,
  # nothing else. Writing anything that later runs would turn every allowed
  # command into arbitrary code: a script it may run, a test, a git hook
  # (core.hooksPath is .beads/hooks), git's own config, or this harness's
  # settings. So no code is writable, and no pytest is allowed either.
  "Edit(scripts/**)" "Write(scripts/**)" "Edit(tests/**)" "Write(tests/**)"
  "Edit(**/*.py)" "Write(**/*.py)" "Edit(**/*.sh)" "Write(**/*.sh)"
  "Edit(.beads/**)" "Write(.beads/**)" "Edit(.claude/**)" "Write(.claude/**)"
  "Edit(.git/**)" "Write(.git/**)" "Edit(pytest.ini)" "Write(pytest.ini)"
  "Edit(venv/**)" "Write(venv/**)"
  "Edit(**/conftest.py)" "Write(**/conftest.py)"
)

run_worker() {
  local config="$1" results="$2" prompt
  prompt="$(sed -e "s|{{CONFIG}}|$config|g" -e "s|{{RESULTS}}|$results|g" \
    -e "s|{{QUEUE}}|$QUEUE|g" -e "s|{{STATUS}}|$STATUS|g" \
    -e "s|{{BRANCH}}|$BRANCH|g" "$PROMPT_FILE")"
  timeout -k 60 "$WORKER_TIMEOUT" claude -p "$prompt" \
    --setting-sources user,project \
    --permission-mode acceptEdits \
    --add-dir "$SESSION_DIR" \
    --allowedTools "${WORKER_ALLOWED_TOOLS[@]}" \
    --disallowedTools "${WORKER_DENIED_TOOLS[@]}" 9>&-
}

while :; do
  # A GATE or FAILED outlives the launch that wrote it, and holds the whole
  # queue, whichever step it was written after: a session may already have
  # taken its step off the queue before finding what it could not decide.
  # Without this, every later launch runs on past the operator's open
  # decision, or re-records the same step on every reclaim. The operator
  # clears it by deleting the status file.
  if [[ -f "$STATUS" ]]; then
    verdict="$(head -1 "$STATUS" | tr -d '[:space:]')"
    if [[ "$verdict" != RECORDED ]]; then
      alert "spot_boot: still waiting on you (${verdict:-no verdict}, after $(cat "$STATUS.config" 2>/dev/null || echo '?'))" \
        "$(tail -n +2 "$STATUS")
Nothing was run. Delete $STATUS once it is dealt with, and relaunch or run $SCRIPT_DIR/spot_boot.sh."
      exit 0
    fi
  fi
  config="$(queue_head)"
  if [[ -z "$config" ]]; then
    alert "spot_boot: the comparison queue is empty" \
      "Nothing left to run. The instance stays up; stop it when you are done."
    exit 0
  fi
  name="$(basename "$config" .yaml)"
  results="results/2026/2026-comparison/${name#2026-comparison-}"

  # The rows must be attributable to a revision that contains their config:
  # committed (not merely staged), and unmodified since.
  if ! git -C "$REPO_ROOT" cat-file -e "HEAD:$config" 2>/dev/null \
     || ! git -C "$REPO_ROOT" diff --quiet HEAD -- "$config"; then
    alert "spot_boot: $config is first in the queue but not committed as it stands" \
      "Nothing was run. Commit it, or take it out of $QUEUE."
    exit 1
  fi

  log "running $config"
  rc=0
  # 9>&-: the lock is this driver's. Inherited, it outlives the driver in any
  # child left running (a batch, a dolt server a `bd` call started), and the
  # next spot_boot.sh on this boot finds it held and runs nothing.
  scripts/run_comparison_step.sh "$config" --wait 9>&- || rc=$?
  case "$rc" in
    0) log "$config complete" ;;
    143)
      alert "spot_boot: $name stopped at a cell boundary (spot notice)" \
        "Finished rows are on /data. The next launch resumes it."
      exit 0 ;;
    *)
      alert "spot_boot: $name exited $rc" \
        "Stopped. See the batch logs under $WORKDIR/logs and $LOG."
      exit 1 ;;
  esac

  if spot_notice_pending; then
    log "spot notice pending; not starting a session the reclaim would cut off"
    exit 0
  fi
  if [[ "$HEADLESS" -eq 0 ]]; then
    alert "spot_boot: $name finished; recording waits for you" \
      "The checkout is not clean on master or $BRANCH, so no headless session ran. Say: continue the 2026 daemon comparison"
    exit 0
  fi

  rm -f "$STATUS"
  printf '%s\n' "$config" > "$STATUS.config"
  log "starting a headless session to record $name"
  wrc=0
  run_worker "$config" "$results" || wrc=$?
  verdict="$(head -1 "$STATUS" 2>/dev/null | tr -d '[:space:]')"
  detail="$(tail -n +2 "$STATUS" 2>/dev/null)"
  log "session exited $wrc, status '${verdict:-none}'"
  case "$verdict" in
    RECORDED)
      # Untracked too: a re-run config written and queued but never committed
      # would otherwise run next, from a revision that does not contain it.
      if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
        alert "spot_boot: $name recorded but the tree is dirty" "$detail"
        exit 1
      fi
      if [[ "$(queue_head)" == "$config" ]]; then
        # Without this the loop re-runs a complete batch and records it again,
        # forever.
        alert "spot_boot: $name recorded but still first in the queue" \
          "Stopped rather than loop. $detail"
        exit 1
      fi
      alert "spot_boot: $name recorded on $BRANCH" "$detail" ;;
    GATE)
      alert "spot_boot: a decision is needed after $name" "$detail"
      exit 0 ;;
    *)
      alert "spot_boot: the session recording $name failed (exit $wrc, status '${verdict:-none}')" \
        "${detail:-No status was written.} Log: $LOG"
      exit 1 ;;
  esac
done
