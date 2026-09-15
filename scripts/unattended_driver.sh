#!/usr/bin/env bash
# Copyright (C) 2026 bgperf2 contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Stage 2 of docs/unattended-execution-plan.md: take one ready item, complete
# it under the review discipline, and go round again -- with no human typing a
# continuation prompt between change sets.
#
# WHAT THIS DOES NOT DO, and why each refusal is here rather than in a comment
# somewhere downstream:
#
#   It does not run on master.  The contract is explicit: unattended work
#   commits to `unattended/measurement`.  Checked before the first iteration
#   and again before each one, because a worker is perfectly capable of
#   checking out a branch mid-run.
#
#   It does not start without a notification channel that just delivered a
#   message.  "A gate nobody sees is worse than stopping" is the plan's rule,
#   and an unattended worker is by construction one nobody is watching, so a
#   channel that is merely *configured* is not enough.
#
#   It checks that **once**, at startup, and then only when it actually has a
#   gate to send.  Re-checking per iteration was tried and is worse: the check
#   does not probe the channel, it *sends* through it, so an idle loop pages
#   the operator every SLEEP_SECONDS -- measured at 6 messages in five seconds
#   with a short sleep, ~48 a day at the default -- on the same channel the
#   gate alert uses.  That trains the operator to filter it, which manufactures
#   the gate nobody sees rather than preventing it.  A channel that breaks
#   mid-run is caught by the send itself, which is a `die`: at most one gate
#   goes unseen and the loop stops there.
#
#   It does not run a benchmark.  Every campaign block is hours of exclusive
#   host time and starting one is the operator's call.  Items labelled for the
#   campaigns are filtered out of the queue, not asked about nicely.
#
#   It does not treat a broken tracker as an empty queue.  See below; this is
#   the mistake the whole exit-code scheme exists to avoid and the first draft
#   made it anyway.
#
# THE EXIT CODES ARE THE POINT, and the plan says why: "A loop that breaks only
# on a non-zero exit spins as fast as the model can decline, because a worker
# that correctly finds nothing to do *succeeds*; one that treats every non-zero
# exit as an empty queue sleeps through a crash."
#
# The plan's sketch had the *worker* signal an empty queue with exit 3. This
# does not: the driver asks the tracker itself, before spending a session, so
# "nothing is ready" is a fact the loop establishes rather than a claim the
# model makes. That removes the case where the model's exit code and the
# tracker disagree -- a model that says 3 while items are ready stalls the
# loop, one that exits 0 having done nothing spins it.
#
# But moving the question to the tracker moves the failure with it, and the
# first draft of this file walked straight into it: `bd` failing (a held Dolt
# lock, a stopped server, an orphaned `venv/bin/python`, a `bd` invoked from a
# directory with no `.beads`) produced *no output*, which read as an empty
# queue, and the loop slept half an hour a round forever. Every `bd` call below
# therefore separates "answered, and the answer is nothing" from "did not
# answer", and only the first sleeps.
#
#   0    a worker completed an item under --once, or --max was reached
#   3    nothing is ready: every remaining item is done or behind a gate
#   1    a real failure -- the worker exited non-zero, a guard refused, the
#        tracker could not be read, or a gate could not be delivered
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

BRANCH="${BGPERF_UNATTENDED_BRANCH:-unattended/measurement}"
SLEEP_SECONDS="${BGPERF_UNATTENDED_SLEEP:-1800}"
# A worker session is unbounded by default, in a loop whose premise is that
# nobody is watching: a stalled one hangs the driver with no output and looks
# exactly like a long item. Generous, because review-until-clean on a real
# change set runs to tens of minutes.
WORKER_TIMEOUT="${BGPERF_UNATTENDED_WORKER_TIMEOUT:-7200}"
# Overridable so the tests can point the driver at a stub tracker and actually
# exercise the empty-queue and tracker-failed paths, rather than asserting
# against whatever the real tracker happens to hold.
BD_BIN="${BGPERF_BD_BIN:-bd}"
# How often the startup channel check may actually send. Defined here with the
# other tunables rather than beside the function that uses it: the validation
# below runs before that point, and under `set -u` reading it there was an
# unbound-variable death on every invocation -- caught by the tests within a
# minute, which is the argument for having them run the thing.
#
# Unvalidated, `abc` is treated as 0 by `(( ))` so the rate limit silently
# switched *off* -- one startup page per process start, which is the
# ~10-a-second storm it exists to prevent -- and `1h` raised an arithmetic
# error on every start.
CHECK_INTERVAL="${BGPERF_NOTIFY_CHECK_INTERVAL:-3600}"
ONCE=0
DRY_RUN=0
MAX_ITERATIONS=0
# Labels whose items this worker may not take, filtered before a session is
# spent rather than after one has read the item and been asked to behave.
#
#   plan:timing-64gb, plan:2026-baseline  benchmarks: hours of exclusive host
#       time, and the operator's call to start.
#   human  **a gate is not work.** An open gate is an unblocked, unclaimed,
#       usually high-priority item, so it sorts to the *front* of `bd ready` --
#       measured: opening one put it at position 1 ahead of every real item.
#       Without this the worker answers its own question, closes the gate it
#       raised, and proceeds on its own guess with a tracker that records a
#       human decision having been made. That is worse than guessing outright,
#       because it leaves evidence that somebody decided.
SKIP_LABELS="${BGPERF_UNATTENDED_SKIP_LABELS:-plan:timing-64gb,plan:2026-baseline}"
# `human` is unioned in below rather than being a default, because a default is
# a thing an operator replaces. Setting BGPERF_UNATTENDED_SKIP_LABELS to the two
# benchmark labels -- the plausible edit, since those are the two the --help
# text talks about -- dropped `human` and re-enabled the worst failure in this
# file: measured against the live tracker, an open gate comes back at position 1
# of `bd ready`, so the next iteration claims the gate the worker just raised.
ALWAYS_SKIP_LABELS="human"

usage() {
  cat <<'EOF'
Usage: scripts/unattended_driver.sh [options]

  --once            take at most one item, then exit
  --max N           stop after N iterations that started a worker
  --dry-run         print the item that would be taken; claim nothing, start
                    no worker
  --sleep SECONDS   how long to wait when nothing is ready (default 1800)

Requires BGPERF_NOTIFY_CMD: a command taking a message on stdin that reaches
the operator. See scripts/notify_gate.sh.

Exit: 0 worked, 3 nothing ready, 1 a real failure.
EOF
}

die() { echo "$*" >&2; exit 1; }

require_number() {
  # An operator typo must not be reported as a run that broke. Without this,
  # `--max` with no value dies as `$2: unbound variable` and `--max abc`
  # survives parsing and dies later inside `[[ ... -gt ... ]]`, both as exit 1
  # -- which this script documents as "a real failure".
  #
  # Zero is refused too, and it is the interesting case: `--max 0` passes a
  # `^[0-9]+$` and then reads as *unlimited* at the bound below, so an operator
  # asking for a bounded run gets an unbounded one; `--sleep 0` turns the idle
  # branch into a tight loop re-querying the tracker, which is the "spins as
  # fast as the model can decline" failure this file opens with.
  [[ "${2:-}" =~ ^[1-9][0-9]*$ ]] \
    || die "$1 needs a whole number above zero, got '${2:-}'"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --once) ONCE=1; shift ;;
    --max) require_number --max "${2:-}"; MAX_ITERATIONS="$2"; shift 2 ;;
    --sleep) require_number --sleep "${2:-}"; SLEEP_SECONDS="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

# After the arguments, because they override these -- validating first refused
# `--sleep 1800` for a bad BGPERF_UNATTENDED_SLEEP the flag was replacing, and
# made `--help` exit 1 instead of printing usage.
require_number BGPERF_UNATTENDED_SLEEP "$SLEEP_SECONDS"
require_number BGPERF_UNATTENDED_WORKER_TIMEOUT "$WORKER_TIMEOUT"
# Zero is meaningful here (always re-check), so this one allows it.
[[ "$CHECK_INTERVAL" =~ ^[0-9]+$ ]] \
  || die "BGPERF_NOTIFY_CHECK_INTERVAL needs a whole number of seconds, got '$CHECK_INTERVAL'"

# `-C` on every call, never a bare `bd`. It auto-discovers `.beads/*.db` from
# the working directory, which this script never sets -- so started from a
# systemd unit with no WorkingDirectory, every tracker call fails, and before
# the fix above that read as an empty queue.
# The driver's own identity, not the human's. `bd` records an assignee as the
# *actor* -- git `user.name`, not `user.email` -- so filtering reconciliation
# by the email matched nothing and `release_stranded_items` was a permanent
# no-op: every path that depends on it silently did nothing, and the item it
# was meant to recover stayed `in_progress` forever. Measured against the real
# tracker: assignee comes back `'bgperf2-unattended'` under this variable and
# `'Justin Pietsch'` without it.
#
# And a *distinct* name rather than the right one, because scoping by the
# human's name would still not tell this driver's claims from the same
# person's interactive ones -- so a startup reconciliation would reopen an item
# they had in flight and hand it to an unattended worker.
UNATTENDED_ACTOR="${BGPERF_UNATTENDED_ACTOR:-bgperf2-unattended}"
bd_cmd() { BEADS_ACTOR="$UNATTENDED_ACTOR" "$BD_BIN" -C "$REPO_ROOT" "$@"; }

# --- guards that read only the environment, before anything is started -------

on_the_branch() {
  local current
  current="$(git -C "$REPO_ROOT" rev-parse --abbrev-ref HEAD)"
  [[ "$current" == "$BRANCH" ]] || die \
    "refusing to run on '$current': unattended work commits to '$BRANCH'.
  git -C $REPO_ROOT checkout $BRANCH"
}

# When the channel was last verified. The check does not probe the channel, it
# *sends* through it, so an unconditional send at startup pages once per
# process start -- and under the `Restart=always, RestartSec=100ms` this file
# assumes, every `die` becomes roughly ten pages a second carrying no
# information about the failure. Strictly worse than both floods the header
# reasons about, and it defeats the announce-once suppression, which sits
# further down than this send.
LAST_CHECK="$(git -C "$REPO_ROOT" rev-parse --absolute-git-dir)/unattended-last-check"

channel_checked_recently() {
  [[ -f "$LAST_CHECK" ]] || return 1
  local then now
  then="$(cat "$LAST_CHECK" 2>/dev/null || echo 0)"
  [[ "$then" =~ ^[0-9]+$ ]] || return 1
  now="$(date +%s)"
  (( now - then < CHECK_INTERVAL ))
}

check_notification() {
  local status=0
  # The *configuration* is checked every time, even inside the rate-limit
  # window: only the delivery probe is skipped. Skipping both let a hand-run
  # `--once` from a shell with no BGPERF_NOTIFY_CMD export start, claim an item
  # and spend a whole worker session with no channel at all -- against this
  # file's own "it does not start without a notification channel".
  if [[ -z "${BGPERF_NOTIFY_CMD:-}" ]]; then
    "$SCRIPT_DIR/notify_gate.sh" --check || true
    die "no notification channel; see the message above. The driver will
not run headless without one -- a gate nobody sees is worse than stopping."
  fi
  if channel_checked_recently; then
    # Verified within the interval; a channel that has broken since is caught
    # by the gate send itself, which is a `die`. That costs at most one gate
    # going unseen -- against a page storm that costs the operator the channel.
    return 0
  fi
  "$SCRIPT_DIR/notify_gate.sh" --check || status=$?
  case $status in
    0) : ;;
    78) die "no notification channel; see the message above. The driver will
not run headless without one -- a gate nobody sees is worse than stopping." ;;
    64) die "the notification settings are malformed; see the message above.
The channel itself may be fine -- fix the setting, not the channel." ;;
    *) die "the notification channel is configured and did not deliver.
Fix it before running unattended: a gate raised now would reach nobody." ;;
  esac
  date +%s > "$LAST_CHECK"
}

# --- the tracker ------------------------------------------------------------

skip_args() {
  local label seen=""
  # The operator's list *and* ALWAYS_SKIP_LABELS, never one or the other.
  IFS=',' read -ra _labels <<< "$SKIP_LABELS,$ALWAYS_SKIP_LABELS"
  for label in "${_labels[@]}"; do
    [[ -z "$label" ]] && continue
    case ",$seen," in *",$label,"*) continue ;; esac
    seen="$seen,$label"
    printf '%s\n%s\n' --exclude-label "$label"
  done
}

# Prints the first id, or nothing. Exits 1 (and says so) if the tracker could
# not be read at all -- which is not an empty queue and must never sleep.
#
# `--claim` on the real path, and it is load-bearing rather than tidy: without
# it a worker that exits 0 without closing its item leaves it open and
# unblocked, and the next round hands back the identical id, unattended,
# forever. `bd ready` excludes in_progress, so claiming is what makes the
# queue advance.
first_ready() {
  local claim="$1"
  local raw status=0 errfile
  mapfile -t _skip < <(skip_args)
  # stderr to its own file, never merged into the JSON. `2>&1` put every notice
  # bd writes -- a Dolt sync line, an upgrade banner, a lock warning -- into the
  # buffer json.loads then choked on, and with `--claim` that happens *after*
  # the item has been claimed: a parse failure silently consumed an item and
  # did no work. Under a systemd `Restart=`, one per start.
  errfile="$(mktemp)"
  if [[ "$claim" == "claim" ]]; then
    raw="$(bd_cmd ready --exclude-type=epic "${_skip[@]}" --claim --json 2>"$errfile")" || status=$?
  else
    raw="$(bd_cmd ready --exclude-type=epic "${_skip[@]}" --json 2>"$errfile")" || status=$?
  fi
  if [[ $status -ne 0 ]]; then
    echo "the tracker could not be read (bd exited $status):" >&2
    head -5 "$errfile" >&2
    rm -f "$errfile"
    return 1
  fi
  rm -f "$errfile"
  printf '%s' "$raw" | "$REPO_ROOT/venv/bin/python" -c '
import json, sys
raw = sys.stdin.read().strip()
if not raw:
    raise SystemExit(0)
try:
    rows = json.loads(raw)
except ValueError:
    # Output that is not JSON is not an empty queue either; say so loudly.
    sys.stderr.write("bd did not return JSON\n")
    raise SystemExit(2)
if isinstance(rows, dict):
    rows = rows.get("issues") or rows.get("data") or []
for row in rows:
    if isinstance(row, dict) and row.get("id"):
        print(row["id"])
        break
'
}

# The ids, not the count. Counting misses a new gate whenever an old one closes
# in the same window -- and the operator answering an earlier gate while a
# worker runs is the *expected* steady state of this design, so open-one
# close-one nets to zero and the new gate is never sent. That is precisely the
# gate nobody sees.
open_gate_ids() {
  local raw status=0 errfile
  # stderr to its own file, for the reason `first_ready` does it: a single
  # notice on stderr -- a Dolt sync line, an upgrade banner, a lock warning --
  # made `json.loads` raise on a perfectly healthy tracker. Fixed there and
  # left here, which at the post-worker call site means a session that just
  # opened a gate dies before the notification: the gate nobody sees.
  errfile="$(mktemp)"
  # `--limit 0`: `bd list` defaults to 50, so this was a *window* onto the
  # gates rather than the set it is documented to be, and new-gate detection
  # survived only on bd's undocumented newest-first ordering. Past 50 open
  # gates, under any other sort, a new one falls outside the window, `comm -13`
  # reports nothing, and no notification is sent -- the gate nobody sees,
  # through the function written to prevent it.
  raw="$(bd_cmd list --label human --status=open --limit 0 --json 2>"$errfile")" || status=$?
  if [[ $status -ne 0 ]]; then
    echo "the tracker could not be read for open gates (bd exited $status):" >&2
    head -5 "$errfile" >&2
    rm -f "$errfile"
    return 1
  fi
  rm -f "$errfile"
  printf '%s' "$raw" | "$REPO_ROOT/venv/bin/python" -c '
import json, sys
raw = sys.stdin.read().strip()
if not raw:
    raise SystemExit(0)
try:
    rows = json.loads(raw)
except ValueError:
    raise SystemExit(2)
if isinstance(rows, dict):
    rows = rows.get("issues") or rows.get("data") or []
for row in sorted(r.get("id", "") for r in rows if isinstance(r, dict)):
    if row:
        print(row)
'
}

# Whether the tracker still shows this item as work in flight. A worker that
# finished closes it; anything else -- a gate, a failure, a timeout, a session
# that simply stopped -- leaves it `in_progress`, and `bd ready` excludes that
# by stored status. Unreleased, such an item never reappears: not when its gate
# is answered, not when a human restarts the loop. It leaves the queue for
# good, silently, while the driver reports "nothing ready".
# Exit 0 = in progress, 1 = definitely not, 2 = could not tell. The third is
# the point: collapsing it into 1 skips the release and strands the item
# forever, which is the failure this whole pair exists to prevent, reached by
# the same read-failure-as-an-answer conflation the header forbids everywhere
# else.
item_still_in_progress() {
  local raw status=0 answer=0
  raw="$(bd_cmd show "$1" --json 2>/dev/null)" || status=$?
  [[ $status -ne 0 ]] && return 2
  printf '%s' "$raw" | "$REPO_ROOT/venv/bin/python" -c '
import json, sys
raw = sys.stdin.read().strip()
if not raw:
    raise SystemExit(2)
try:
    row = json.loads(raw)
except ValueError:
    raise SystemExit(2)
if isinstance(row, list):
    row = row[0] if row else {}
if isinstance(row, dict) and isinstance(row.get("issue"), dict):
    row = row["issue"]
raise SystemExit(0 if row.get("status") == "in_progress" else 1)
' && return 0 || answer=$?
  # Clamped. The function returns the *pipeline's* status, so an orphaned
  # `venv/bin/python` -- which this header names as a failure mode and
  # CLAUDE.md says a distro upgrade causes -- gives 127, which matched neither
  # `-eq 0` nor `-eq 2` at the call site: no release, no reconcile, nothing
  # printed, and the claim stranded. Only 1 means "definitely not"; everything
  # else is the third outcome the docstring promises.
  [[ $answer -eq 1 ]] && return 1
  return 2
}

# Whether the item would be handed back by the very next query. The sound test
# for the spin, because it asks the question the loop will actually ask.
# 0 = yes, 1 = no, 2 = could not tell. The third separated for the reason the
# header gives for every other `bd` call: folded into "no", a failed read means
# the spin guard does not fire and `--once` exits **0** -- reported as a
# completed item -- for an item released unblocked and unchanged, which the
# operator's next `--once` is then handed again.
item_is_ready_again() {
  local again
  again="$(first_ready peek)" || return 2
  [[ "$again" == "$1" ]]
}

release_item() {
  local err status=0
  err="$(bd_cmd update "$1" --status open 2>&1 >/dev/null)" || status=$?
  if [[ $status -ne 0 ]]; then
    # `die`, not a warning. This is the one failure path in this file whose
    # consequence is permanent: the item stays `in_progress`, `bd ready`
    # excludes it by stored status forever, `item_is_ready_again` therefore
    # says false so nothing else stops the loop, and the driver reports
    # "nothing ready" over real work that has silently left the queue. A
    # warning here goes to the terminal nobody is reading, which is this
    # script's own premise.
    echo "$err" | head -5 >&2
    die "could not release $1 (bd exited $status); it is stuck in_progress and
would never be offered again. Release it by hand before restarting:
  bd -C $REPO_ROOT update $1 --status open"
  fi
}

# Exactly what the prompt's definition of done requires, and nothing else.
# Read as a list of what an unattended session may do to this machine.
# **Trailing `*` only.** Bash permission rules are prefix matches, not globs --
# every rule in this repo's own `.claude/settings.json` is that shape -- so the
# `Bash(git -C * commit *)` entries this list used to carry matched nothing,
# and the worker (which CLAUDE.md and the prompt both push toward `git -C`)
# could not commit. Round eight's defect in a second form.
#
# `Bash(git -C *)` is deliberately **not** the fix. It would match, and it
# would also permit `git -C <dir> push`, which no prefix rule can then deny --
# `Bash(git -C * push *)` has the same dead wildcard. Leaving the `-C` form out
# entirely means any `git -C` command needs a permission decision nobody can
# give, so it is denied. The worker uses plain `git`, which works because
# `run_worker` starts it in $REPO_ROOT, and which satisfies CLAUDE.md's rule --
# that rule prohibits `cd`, not git in a directory one is already in.
WORKER_ALLOWED_TOOLS=(
  Edit Write Read Glob Grep Skill TodoWrite
  "Bash(git add *)"
  "Bash(git commit *)"
  "Bash(git status *)"
  "Bash(git diff *)"
  "Bash(git log *)"
  "Bash(git show *)"
  "Bash(bd *)"
  "Bash(venv/bin/python -m pytest *)"
)
# Deliberately absent: `Bash(venv/bin/python -c *)`. A prefix-matched `-c`
# auto-approves arbitrary code, so a worker could reach `git push` or `docker`
# through a one-liner and the deny rules below would never see the command --
# the tool input is the python, not the thing it runs. Nothing in the prompt
# asks for it, and `-m pytest` already covers the definition of done.
# Stated as well as omitted. An omission is undone by anyone widening the allow
# list later; a denial is not, and these two are the ones that would take an
# unattended mistake off this machine or onto the host for hours.
WORKER_DENIED_TOOLS=(
  "Bash(git push *)" "Bash(docker *)"
)

WORKER_PROMPT_FILE="$SCRIPT_DIR/unattended_worker_prompt.md"
[[ -f "$WORKER_PROMPT_FILE" ]] || die "no worker prompt at $WORKER_PROMPT_FILE"

run_worker() {
  local item="$1"
  local prompt
  # `{{BRANCH}}` as well as `{{ITEM}}`: the prompt named the branch literally
  # while the driver's is overridable, so a run on any other branch told the
  # worker it was somewhere it was not -- and the worker's own "if you find
  # yourself on another branch, stop" then fires against a correct run, or it
  # commits to the branch the prompt named.
  # `{{REPO}}` too: the prompt named `/data/bgperf2` literally while the driver
  # derives REPO_ROOT from BASH_SOURCE, so a run from a second checkout told
  # the worker to edit and commit in a *different* repository from the one the
  # branch guard and the dirty-tree check are watching. The same defect as the
  # branch one, one round later.
  prompt="$(sed -e "s|{{ITEM}}|$item|g" -e "s|{{BRANCH}}|$BRANCH|g" \
    -e "s|{{REPO}}|$REPO_ROOT|g" "$WORKER_PROMPT_FILE")"
  # `acceptEdits` auto-approves Edit and Write only; a Bash call outside the
  # project allowlist still needs a permission decision, and in `-p` there is
  # nobody to give one, so it is denied. The allowlist in
  # `.claude/settings.json` carries `pytest` and three read-only `bgperf2.py`
  # subcommands -- no `git`, no `bd` -- so the prompt's definition of done
  # (commit to the branch, close the item, or open a gate with `bd dep add`)
  # was **unreachable**: the worker would edit, fail to commit, exit 0, and the
  # tree check would then blame it and leave the tree dirty for every
  # subsequent start. Never exercised, because the one recorded run died on the
  # spend limit first.
  #
  # So the tools are named here rather than left to the ambient allowlist, and
  # this list is the security boundary: it is what the worker may do, and
  # everything absent from it stops the session instead of proceeding. `git
  # push` and `docker` are absent deliberately -- unattended work does not
  # leave the branch and does not start a benchmark -- and are denied
  # explicitly as well, because a deny cannot be widened by a future edit to
  # the allow list.
  # `-k`: plain `timeout` sends SIGTERM and then waits indefinitely for a child
  # that blocks or ignores it -- a wedged `docker exec`, a process in
  # uninterruptible sleep -- which hangs the loop exactly as an unbounded
  # session would, defeating the bound this line exists to impose.
  # In $REPO_ROOT, not the driver's inherited cwd. Every `bd` and `git` call
  # here is `-C` because a systemd unit with no WorkingDirectory leaves cwd at
  # `/` -- and a worker started there resolves the project `CLAUDE.md`, the
  # `.claude/` hooks (review-before-commit, the invariants guard) and its own
  # `venv/bin/python -m pytest tests/` against the wrong directory. The entire
  # discipline the prompt consists of would silently not be in force.
  (cd "$REPO_ROOT" && timeout -k 60 "$WORKER_TIMEOUT" \
     claude -p "$prompt" \
       --permission-mode acceptEdits \
       --allowedTools "${WORKER_ALLOWED_TOOLS[@]}" \
       --disallowedTools "${WORKER_DENIED_TOOLS[@]}")
}

# --- the loop ---------------------------------------------------------------

# A gate whose notification failed on a previous run is still owed, and the
# id-diff below cannot rediscover it. Sent before anything else, and the marker
# cleared only once it is delivered.
# Under .git/, not the repo root. At the root it is an untracked file the
# driver's own dirty-tree guard would blame the next worker for -- and a
# `git add -A` landing while it exists makes it tracked, which is the accident
# the results*.tgz rules were just added for. .git/ is never a worktree path,
# so nothing can stage it and no status check sees it.
# `--absolute-git-dir`, not `--git-dir`: the latter prints `.git`, relative to
# $REPO_ROOT, and this driver deliberately never cd's -- so under a systemd
# unit with no WorkingDirectory both markers resolved to `/.git/...`, where the
# append fails and the guard that reads them sees no file and returns clean.
UNDELIVERED="$(git -C "$REPO_ROOT" rev-parse --absolute-git-dir)/unattended-undelivered-gates"
# Items whose worker failed, so a restart does not hand back the same poisoned
# one forever. The header assumes a systemd `Restart=`; without this the
# restart claims the identical item, it fails identically, and the loop is hot
# with no notification and no record. Not hypothetical -- it is the spend-limit
# failure recorded as `bgperf2-cqi`.
FAILED_ITEMS="$(git -C "$REPO_ROOT" rev-parse --absolute-git-dir)/unattended-failed-items"

note_failed_item() {
  printf '%s\n' "$1" >> "$FAILED_ITEMS"
}

# Cleared when the item is completed, so a later failure starts from zero.
clear_announced_item() {
  [[ -f "$FAILED_ITEMS.announced" ]] || return 0
  grep -v -x -F "$1" "$FAILED_ITEMS.announced" \
    > "$FAILED_ITEMS.announced.tmp" 2>/dev/null || true
  mv "$FAILED_ITEMS.announced.tmp" "$FAILED_ITEMS.announced"
}

clear_failed_item() {
  # The announcement marker too, so an item dealt with and later failing again
  # is reported afresh rather than silently.
  clear_announced_item "$1"
  [[ -f "$FAILED_ITEMS" ]] || return 0
  grep -v -x -F "$1" "$FAILED_ITEMS" > "$FAILED_ITEMS.tmp" 2>/dev/null || true
  mv "$FAILED_ITEMS.tmp" "$FAILED_ITEMS"
}

refuse_a_repeatedly_failing_item() {
  local item="$1" count=0
  # Releases before dying. It ran after the claim, so refusing left the item
  # `in_progress` -- and `bd ready` excludes that by stored status, so the item
  # the operator was being asked to deal with was the one they could no longer
  # see. The notification told them to clear the record and said nothing about
  # releasing it.
  [[ -f "$FAILED_ITEMS" ]] || return 0
  # The tail, so this is "failed the last two times" rather than "failed twice
  # ever". Lifetime, an item that failed once, was fixed, and failed once again
  # months later was refused at count 2 under a notification claiming it had
  # failed on every attempt.
  count="$(tail -20 "$FAILED_ITEMS" | grep -c -x -F "$item" || true)"
  # The clear goes **above** the early return, not below it. Below, it was
  # unreachable for every value of `count` that could reach it -- dead code
  # that read as a fix, and the test grepped its position in the source rather
  # than exercising it, so 76 tests passed over the regression it was written
  # against. An operator who clears $FAILED_ITEMS as both die messages instruct
  # would otherwise leave a stale entry that silences the next real page.
  if [[ "$count" -lt 2 ]]; then
    clear_announced_item "$item"
    return 0
  fi
  # Two failures is enough: one is a blip, two in a row is the item. The
  # operator is told, because a loop that quietly skips work is the idle
  # worker this whole design is against.
  # Sent once per item, not once per restart. It notifies, releases and dies
  # without appending to $FAILED_ITEMS, so the count stays at the threshold and
  # the item stays ready -- and under `Restart=always` (RestartSec=100ms) that
  # is a page every tenth of a second until a human intervenes. The file's own
  # opening argument rejects the per-iteration check for ~48 pages a day
  # because it trains the operator to filter the channel; this was worse, on
  # the same channel.
  local announced="$FAILED_ITEMS.announced"
  # Above the `-f` guard below, because "clear $FAILED_ITEMS" reads as `rm` --
  # and with the file gone the function returned before ever reaching the
  # clear, so the stale marker survived and silenced the next real page. The
  # test passed only because its fixture wrote an *empty* file instead of
  # omitting it. Fourth round on this marker; `clear_failed_item` already does
  # it in this order.
  if [[ ! -f "$FAILED_ITEMS" ]]; then
    clear_announced_item "$item"
    return 0
  fi
  if grep -q -x -F "$item" "$announced" 2>/dev/null; then
    release_item "$item"
    die "$item has failed $count times and was already reported; stopping.
Clear $FAILED_ITEMS once it is dealt with (the announcement marker beside it
is cleared automatically when the count drops)."
  fi
  printf '%s\n' "$item" >> "$announced"

  # Recorded before sending, and the send is not `|| true`. Every other send
  # in this file dies and leaves an owed-notification marker; this one alone
  # swallowed a failure, so an operator whose channel had broken since startup
  # was never told the loop had stopped -- the only record being a message on
  # the terminal this script's premise says nobody reads.
  if ! "$SCRIPT_DIR/notify_gate.sh" \
      "bgperf2: $item has failed $count times; the loop is stopping" \
      "Its worker failed on every attempt. It needs a human before the queue can
move past it -- either fix what it trips over, or gate it. Clear the record at
$FAILED_ITEMS once it is dealt with."; then
    printf '%s\n' "$item has failed $count times and the loop stopped" \
      > "$UNDELIVERED"
    release_item "$item"
    die "$item has failed $count times and the channel is also failing; both
are recorded in $UNDELIVERED and $FAILED_ITEMS."
  fi
  release_item "$item"
  die "$item has failed $count times; stopping rather than restarting onto it.
It has been released, so it is visible again once you clear $FAILED_ITEMS."
}

# Every item this driver left `in_progress`, released. The claim only ever
# means "a worker is on this right now", so anything still claimed when no
# worker is running is stranded -- and `bd ready` excludes it by stored status,
# so it has silently left the queue.
#
# Two paths need this and neither can name the item: `bd ready --claim` mutates
# state *inside* bd and the parse after it can still fail (non-JSON on stdout,
# or an orphaned venv giving 127), and a signal between the claim and the
# release leaves no chance to say which. So this asks the tracker what is
# claimed instead of guessing.
release_stranded_items() {
  local raw status=0 ids
  # Scoped to $UNATTENDED_ACTOR, which only this driver claims under. Unscoped
  # it reopened *every* in-progress item -- including one a human had claimed
  # interactively, which the next `--claim` would then hand to an unattended
  # worker, two sessions editing the same work.
  raw="$(bd_cmd list --status=in_progress --assignee "$UNATTENDED_ACTOR" \
           --limit 0 --json 2>/dev/null)" || status=$?
  # Non-zero, not 0: the caller says "any claim it had already taken has been
  # released", and the only way to reach that caller is `bd` being unhealthy --
  # which is exactly when this read fails too. Swallowed, the operator was told
  # the claim was clean while it sat `in_progress`, which `bd ready` then
  # excludes forever. "A pass that failed and a pass that has not run are never
  # described by one clause", applied to the claim.
  [[ $status -ne 0 ]] && return 1
  ids="$(printf '%s' "$raw" | "$REPO_ROOT/venv/bin/python" -c '
import json, sys
raw = sys.stdin.read().strip()
if not raw:
    raise SystemExit(0)
try:
    rows = json.loads(raw)
except ValueError:
    raise SystemExit(0)
if isinstance(rows, dict):
    rows = rows.get("issues") or rows.get("data") or []
for row in rows:
    if isinstance(row, dict) and row.get("id"):
        print(row["id"])
' 2>/dev/null || true)"
  local id
  for id in $ids; do
    echo "releasing stranded claim on $id" >&2
    bd_cmd update "$id" --status open >/dev/null 2>&1 || true
  done
}

# A signal between the claim and the release strands the item, and this loop
# runs under a systemd `Restart=` on a spot instance that is reclaimed without
# warning -- so that window is the one most likely to be hit in production,
# not a corner.
CURRENT_ITEM=""
on_signal() {
  if [[ -n "$CURRENT_ITEM" ]]; then
    # Only if it is *observed* `in_progress`. `CURRENT_ITEM` stays set through
    # the gate read, the gate send (bounded at 60s), the comm and the tree
    # check -- all after a successful worker has closed its item -- so an
    # unconditional release here reopened closed, committed work on exactly
    # the signal the header calls most likely: the spot reclaim. The same rule
    # the release site states, which this did not follow.
    if item_still_in_progress "$CURRENT_ITEM"; then
      echo "signalled while holding $CURRENT_ITEM; releasing it" >&2
      bd_cmd update "$CURRENT_ITEM" --status open >/dev/null 2>&1 || true
    fi
  fi
  exit 143
}
trap on_signal TERM INT

resend_undelivered() {
  [[ -f "$UNDELIVERED" ]] || return 0
  if "$SCRIPT_DIR/notify_gate.sh" \
      "bgperf2: gate(s) from an earlier run were never delivered" \
      "$(cat "$UNDELIVERED")"; then
    rm -f "$UNDELIVERED"
  else
    die "a gate from an earlier run is still undelivered and the channel is
still failing; fix the channel before running unattended. The ids are in
$UNDELIVERED."
  fi
}

# One driver per checkout. `release_stranded_items` at startup sets every
# in-flight claim of this actor back to `open`, so a second driver -- the
# operator running `--once` by hand while the systemd unit works -- reopens the
# first one's item, claims it, and two `claude` sessions edit and commit the
# same item in the same worktree. Scoping the reconciliation by actor fixed the
# human-vs-driver case and created the driver-vs-driver one.
#
# The flock is released when the holder dies, SIGKILL included, so a reclaimed
# host leaves an inert file rather than a stuck lock.
DRIVER_LOCK="$(git -C "$REPO_ROOT" rev-parse --absolute-git-dir)/unattended.lock"
exec 8>"$DRIVER_LOCK"
if ! flock -n 8; then
  die "another unattended driver is already running against $REPO_ROOT.
Two would reopen and re-claim each other's in-flight items."
fi

on_the_branch
# A dirty tree at startup is the operator's, and saying so here is the only
# place it can be said honestly: mid-loop the driver cannot tell their edit
# from the worker's.
if [[ $DRY_RUN -eq 0 ]]; then
  startup_dirty="$(git -C "$REPO_ROOT" status --porcelain)"
  if [[ -n "$startup_dirty" ]]; then
    echo "$startup_dirty" | head -10 >&2
    # Paged, once. A worker that failed *after* editing leaves the tree dirty,
    # and this guard then refuses before the loop is ever entered -- so
    # `refuse_a_repeatedly_failing_item`, which lives inside the loop, never
    # runs, no second failure accumulates, and no failure-specific page is ever
    # sent. The driver is wedged until a human happens to look, which is the
    # state this whole design is against. That is also the likeliest shape of a
    # worker failure: a session that edits, then errors or hits the timeout.
    wedged="$(git -C "$REPO_ROOT" rev-parse --absolute-git-dir)/unattended-wedged"
    if [[ ! -f "$wedged" ]]; then
      # `touch` only on success, and record the debt otherwise. Marked first,
      # a channel that was down at this moment made the send never happen and
      # never be retried -- the only silent drop in a file where every other
      # send either dies or records an owed notification, guarding the state it
      # calls "wedged until a human happens to look".
      if "$SCRIPT_DIR/notify_gate.sh" \
          "bgperf2: the unattended driver is stopped on a dirty tree" \
          "$(printf 'It cannot start until the working tree is clean.\n\n%s\n' \
               "$(echo "$startup_dirty" | head -20)")"; then
        touch "$wedged"
      else
        printf '%s\n' "the driver is stopped on a dirty tree in $REPO_ROOT" \
          > "$UNDELIVERED"
      fi
    fi
    die "the tree is not clean; an unattended worker would review and commit
this under whatever item it takes first. Commit, stash or clean it."
  fi
  rm -f "$(git -C "$REPO_ROOT" rev-parse --absolute-git-dir)/unattended-wedged"
fi
# A dry run raises no gates, so it needs no channel -- and checking does not
# probe the channel, it *sends* through it, so an operator iterating on a
# --dry-run invocation pages themselves once per attempt on the alert channel.
# That is what the per-iteration re-check was backed out for.
if [[ $DRY_RUN -eq 0 ]]; then
  check_notification
  resend_undelivered
  # A predecessor that was killed rather than signalled -- a reclaim past its
  # two-minute warning, an OOM kill, a stop that hit TimeoutStopSec while the
  # trap was queued behind a foreground worker -- never ran `on_signal`, so its
  # item is still `in_progress` and `bd ready` excludes it by stored status.
  # Nothing else would ever release it.
  release_stranded_items
fi

worked=0
while :; do
  on_the_branch

  if ! gates_before="$(open_gate_ids)"; then
    die "refusing to continue without being able to read the gates: a gate
opened now could not be told from one already answered."
  fi

  if [[ $DRY_RUN -eq 1 ]]; then
    item="$(first_ready peek)" || die "the tracker could not be read"
  else
    if ! item="$(first_ready claim)"; then
      # The claim may already have landed inside bd before the parse failed,
      # and this cannot know which item it was.
      if release_stranded_items; then
        die "the tracker could not be read; any claim it had already taken has
been released."
      fi
      die "the tracker could not be read, and the reconcile could not run
either -- so a claim it had already taken may still be held. Check:
  bd -C $REPO_ROOT list --status=in_progress --assignee $UNATTENDED_ACTOR"
    fi
  fi

  if [[ -z "$item" ]]; then
    echo "nothing ready ($(printf '%s' "$gates_before" | grep -c . || true) open gate(s))"
    if [[ $ONCE -eq 1 || $DRY_RUN -eq 1 ]]; then
      exit 3
    fi
    # Sleep rather than exit, so the loop resumes the moment a human closes a
    # gate. Exiting here is what makes an unattended worker need a human to
    # restart it, which is the thing being removed. It does **not** count
    # against --max: that reads as "N items", and a night of sleeping is not
    # ten completed items.
    sleep "$SLEEP_SECONDS"
    continue
  fi

  if [[ $DRY_RUN -eq 0 ]]; then
    # After the dry-run exit below, never before it. This pages the operator
    # *and* calls `release_item`, which is a tracker write -- so a `--dry-run`
    # taken to see what was next, on a queue whose head had failed twice,
    # notified on the alert channel and wrote to the tracker, against a
    # `--help` that promises "claim nothing, start no worker".
    refuse_a_repeatedly_failing_item "$item"
  fi

  CURRENT_ITEM="$item"
  worked=$((worked + 1))
  echo "=== item $worked: $item"
  if [[ $DRY_RUN -eq 1 ]]; then
    bd_cmd show "$item" 2>/dev/null | head -3 || true
    exit 0
  fi

  tree_before="$(git -C "$REPO_ROOT" status --porcelain)"

  status=0
  run_worker "$item" || status=$?
  if [[ $status -eq 124 ]]; then
    echo "worker timed out after ${WORKER_TIMEOUT}s on $item" >&2
  fi

  # Recorded first, before the release and before anything that can `die`.
  # `note_failed_item` sat at the bottom, past six exits -- the gate read, the
  # gate send, the comm comparison, both spin refusals and the dirty-tree
  # guard -- so a worker that failed *and* tripped any of those wrote no record
  # at all, and the systemd restart came straight back onto the same item. The
  # guard was added for exactly that loop.
  if [[ $status -ne 0 ]]; then
    note_failed_item "$item"
  fi

  # Released here -- immediately, before anything below that can `die`. It sat
  # after the gate block, so the two exits in between (the gate read failing,
  # and the gate *send* failing, which the header explicitly plans for) left
  # the item claimed: `bd ready` excludes `in_progress` by stored status, so
  # when the operator answered that gate the item never came back. The
  # permanent failure `release_item` describes, reached on the path most likely
  # to hit it. The claim only ever means "a worker is on this right now", so it
  # ends when the worker does.
  #
  # **Only** on an observed `in_progress`. Releasing on "cannot tell" was
  # wrong in the one direction that destroys work: `bd update --status open`
  # on a *closed* issue reopens it, so a transient `bd show` failure after a
  # worker had committed and closed its item put finished work back in the
  # queue -- and then the spin guard saw it ready and died claiming the worker
  # had left it unchanged, which was false. "Releasing an already-open item is
  # harmless" does not extend to a closed one.
  #
  # The stranded-claim case that reasoning was meant to cover is handled by
  # `release_stranded_items`, which asks the tracker what is actually claimed
  # rather than guessing from a failed read.
  in_progress=0
  item_still_in_progress "$item" || in_progress=$?
  if [[ $in_progress -eq 0 ]]; then
    release_item "$item"
  elif [[ $in_progress -eq 2 ]]; then
    echo "could not read $item's status; leaving it as it is and reconciling" >&2
    release_stranded_items
  fi

  # After the worker, and by id: the driver notices the gate, never the worker.
  # A model that forgets to notify produces exactly the failure the rule is
  # about, and produces it silently.
  if ! gates_after="$(open_gate_ids)"; then
    die "a worker just ran and the gates could not be read; stopping rather
than continuing blind."
  fi
  # LC_ALL=C: `open_gate_ids` sorts in Python codepoint order and GNU `comm`
  # compares under LC_COLLATE, so a locale that disagrees makes comm error
  # ("file N is not in sorted order") -- and swallowed, that read as "no new
  # gates" and sent nothing. The gate nobody sees, through the function
  # written to prevent it. The status is checked rather than `|| true`d for
  # the same reason.
  comm_status=0
  new_list="$(LC_ALL=C comm -13 <(printf '%s\n' "$gates_before") \
                                <(printf '%s\n' "$gates_after"))" || comm_status=$?
  if [[ $comm_status -ne 0 ]]; then
    die "could not compare the gate sets (comm exited $comm_status); stopping
rather than assuming no gate was opened."
  fi
  new_gates="$(printf '%s' "$new_list" | grep -c . || true)"
  if [[ "$new_gates" -gt 0 ]]; then
    if ! "$SCRIPT_DIR/notify_gate.sh" \
        "bgperf2: $new_gates gate(s) opened, a decision is needed" \
        "$(printf 'new:\n%s\n' "$new_list")"; then
      # Recorded before dying. On the next start `gates_before` already holds
      # this gate, so `comm -13` can never report it again -- under a systemd
      # `Restart=` the driver comes back, works the remaining items, and the
      # one gate that failed to deliver is never mentioned by any means. The
      # marker is what a restart reads to know it still owes a notification.
      # `$UNDELIVERED`, which is what `resend_undelivered` reads -- the fix for
      # this went to the read site only, so the write landed at the repo root
      # under a different name: the marker was never found on restart *and* it
      # sat untracked in the worktree, where the dirty-tree guard blamed every
      # later item for it. And `$new_list`, not every open gate: the resend
      # otherwise re-pages gates already delivered.
      printf '%s\n' "$new_list" > "$UNDELIVERED"
      # Stopping, not warning. A warning here goes to a terminal nobody is
      # reading -- which is the premise of the whole script -- and the loop
      # would carry on accumulating unseen gates for as long as it ran.
      die "a gate was opened and the notification failed; stopping rather than
running on with gates nobody can see."
    fi
  fi


  # Whether *this item* is ready again -- not whether some gate appeared
  # somewhere. A worker that creates a gate and fails the `bd dep add` gates
  # nothing, and counting gates then reads that as explained: the item is
  # released unblocked, the next round hands back the identical id, and the
  # gate notification makes the round look normal while the loop spins.
  if [[ $status -eq 0 ]]; then
    ready_again=0
    item_is_ready_again "$item" || ready_again=$?
    case $ready_again in
      0) # Recorded, or the restart loops hot on it: the item is released and
         # the tree is clean, so every startup guard passes, the same item is
         # claimed, a full session runs, and it dies here again -- burning a
         # session a cycle with nothing in $FAILED_ITEMS and no page. A model
         # that declines the work is the likelier way here than a crash, and
         # only crashes were being counted.
         note_failed_item "$item"
         die "worker exited 0 but left $item ready and unchanged; stopping
rather than handing it back to the next iteration forever. If it needs a
decision it needs a gate blocking it, and this one has none." ;;
      2) die "worker exited 0 and the tracker could not be read to find out
whether $item advanced; stopping rather than reporting a completed item this
cannot confirm." ;;
    esac
  fi

  # The tree, between items. "Commit your work" was left entirely to the
  # prompt, and this driver's whole design is that a rule a model can forget is
  # enforced here -- gates are diffed by id for exactly that reason. A worker
  # that closes its item but leaves an unstaged hunk or an untracked file
  # behind hands it to the next worker, who reviews and commits it under a
  # different item, with nothing in the tracker or the commit message saying
  # so.
  # Against the baseline taken before the worker, not an absolute emptiness.
  # Absolute, any pre-existing untracked file -- a stray log, an editor
  # swapfile, the operator's own half-finished edit, the misplaced marker this
  # same round fixed -- stopped the driver on the *next* item with a message
  # naming the wrong culprit. Measured: a stub worker that touched nothing was
  # blamed for this branch's own staged changes.
  tree_after="$(git -C "$REPO_ROOT" status --porcelain)"
  if [[ "$tree_after" != "$tree_before" ]]; then
    LC_ALL=C comm -13 <(printf '%s\n' "$tree_before" | LC_ALL=C sort) \
                      <(printf '%s\n' "$tree_after" | LC_ALL=C sort) \
      | head -10 >&2
    die "the worker left changes in the tree after $item; stopping rather than
letting the next item's review and commit absorb them."
  fi

  if [[ $status -ne 0 ]]; then
    echo "worker exited $status on $item; stopping and leaving the tree" >&2
    exit 1
  fi
  # Reached only on a clean completion, so the count above means "the last two
  # attempts", not "twice in this item's life".
  clear_failed_item "$item"
  CURRENT_ITEM=""

  [[ $ONCE -eq 1 ]] && exit 0
  if [[ $MAX_ITERATIONS -gt 0 && $worked -ge $MAX_ITERATIONS ]]; then
    echo "reached --max $MAX_ITERATIONS"
    exit 0
  fi
done
