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
# Send one out-of-band message to the operator, or fail loudly.
#
# This exists because of one line in docs/unattended-execution-plan.md:
# "A gate nobody sees is worse than stopping." Stopping is at least visible in
# the terminal. A gate that is opened, never surfaced, and silently blocks the
# only ready item leaves a worker that looks busy and is idle -- and an
# unattended worker is, by construction, one nobody is watching.
#
# So this is deliberately not a best-effort notifier. It has no fallback that
# "works" by writing somewhere nobody reads: a local file is a gate nobody
# sees, which is the thing being prevented, so falling back to one would
# satisfy the code and defeat the rule. With no channel configured it exits
# non-zero and says so, and `unattended_driver.sh` refuses to start.
#
# The channel itself is the operator's, supplied as BGPERF_NOTIFY_CMD: any
# command that takes the message on stdin and exits 0 when the operator will
# see it. Deliberately not a list of integrations -- a webhook URL or a token
# is a credential this repository must not carry, and which service to page is
# a human decision this worker may not make for itself.
#
#   BGPERF_NOTIFY_CMD='curl -sSf -d @- https://ntfy.sh/my-topic'
#   BGPERF_NOTIFY_CMD='xargs -0 -I{} tmux display-message {}'
#   BGPERF_NOTIFY_CMD='cat >> /data/gates.log'      # a sink, for testing only
#
# The command must actually *consume stdin*, and --check cannot tell you that
# it does. `tmux display-message -p` was listed here and is the trap: it never
# reads stdin and prints to stdout, which this sends to /dev/null, so it exits
# 0 and --check reports a channel that delivers nothing. Whether `printf` then
# takes SIGPIPE before filling the pipe buffer is a race, so the same command
# can report success or failure from one run to the next.
#
# Usage:
#   notify_gate.sh --check                 verify the channel is configured and
#                                          delivers, without claiming a gate
#   notify_gate.sh "subject" ["body"]      send one message
set -euo pipefail

CHECK=0
if [[ "${1:-}" == "--check" ]]; then
  CHECK=1
  shift
fi

if [[ -z "${BGPERF_NOTIFY_CMD:-}" ]]; then
  cat >&2 <<'MSG'
no BGPERF_NOTIFY_CMD is set, so there is no way to tell the operator a gate
was opened.

An unattended worker that opens a gate nobody sees looks busy and is idle,
which the plan calls worse than stopping -- so this refuses rather than
writing to a file nobody reads.

Set it to any command that takes the message on stdin and exits 0 when the
operator will actually see it, for example:

  export BGPERF_NOTIFY_CMD='curl -sSf -d @- https://ntfy.sh/<your-topic>'

Which channel to use is your decision, not the worker's; see the gate recorded
under `bd human list`.
MSG
  exit 78   # EX_CONFIG: the configuration is missing, not the send failing
fi

if [[ $CHECK -eq 1 ]]; then
  subject='bgperf2 unattended driver: notification check'
  body='This is the startup check. If you are reading it, gates will reach you.'
else
  subject="${1:-bgperf2 unattended worker}"
  body="${2:-}"
fi

message="$(printf '%s\n' "$subject")"
if [[ -n "$body" ]]; then
  message="$(printf '%s\n\n%s\n' "$subject" "$body")"
fi
# Always say which host and checkout, because the operator may be running
# several and a gate that does not say where it was raised costs a hunt.
# The startup check gets it too, and needs it most: a check that does not name
# its host confirms only that *something* can reach the operator, which is the
# one thing they already knew.
message="$(printf '%s\n\n-- %s:%s @ %s\n' "$message" "$(hostname)" \
  "$(git -C "$(dirname "${BASH_SOURCE[0]}")/.." rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')" \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)")"

# `eval` because the operator's command is a command line, not a program name:
# `curl -sSf -d @- <url>` has to keep its arguments. It comes from the
# environment of whoever started the driver, which is the same trust boundary
# as the shell they started it from.
# The channel's own status, not the pipeline's. Under `pipefail` a command
# that exits 0 after reading only part of the message -- `head -1`, a curl that
# closes the body early, any reader that returns before draining -- gives
# `printf` a SIGPIPE and the pipeline 141, so a message that *was* delivered
# reported "the operator was NOT told". In the driver that is a `die`, so a
# working channel stopped the loop; and because whether printf fills the pipe
# buffer first is a race, the same channel could pass --check at startup and
# fail on the first real gate.
# `set +e` as well as `+o pipefail`, and neither replaced by a `|| true`:
# errexit alone aborts on the failing pipeline before PIPESTATUS can be read,
# which exits 1 having printed nothing -- the silent version of the failure
# this branch exists to report -- while `|| true` makes the pipeline part of a
# compound command and resets PIPESTATUS to `true`'s, so under `set -u` the
# read below dies as an unbound variable instead.
# Bounded. The documented `curl -sSf -d @- https://ntfy.sh/<topic>` carries no
# --max-time, so against a black-holed host it hangs -- which hangs the startup
# check with no output, and worse hangs the post-worker gate send while a
# worker's changes sit uncommitted. The driver bounds its worker with
# `timeout -k` for exactly this reason; the channel had no bound at all.
NOTIFY_TIMEOUT="${BGPERF_NOTIFY_TIMEOUT:-60}"
# Validated, or `timeout` exits 125 on `60s`/`abc` and this reports it as
# "the operator was NOT told" -- which the driver turns into "the channel is
# configured and did not deliver. Fix it before running unattended", pointing
# at a channel that is fine. The same class `require_number` exists for in the
# driver, applied there to two of the three numbers and not to this one.
if [[ ! "$NOTIFY_TIMEOUT" =~ ^[1-9][0-9]*$ ]]; then
  echo "BGPERF_NOTIFY_TIMEOUT must be a whole number of seconds above zero," >&2
  echo "got '$NOTIFY_TIMEOUT'" >&2
  # 64 (EX_USAGE), not 78: the driver maps 78 to "no notification channel ...
  # the driver will not run headless without one", so a `60s` typo told the
  # operator to configure a channel that was already configured and working.
  exit 64
fi
set +e +o pipefail
# stdout to /dev/null for the `tmux` trap above; **stderr kept**, because it
# is the only thing that says *why* a channel failed. Discarded, a bad topic or
# a TLS error reported `exit 6` and the command string, and the driver then
# refused to start with "fix it before running unattended" and nothing to fix
# it from.
printf '%s' "$message" | timeout -k 10 "$NOTIFY_TIMEOUT" \
  bash -c "$BGPERF_NOTIFY_CMD" >/dev/null
channel_status="${PIPESTATUS[1]}"
set -e -o pipefail
if [[ "$channel_status" -ne 0 ]]; then
  echo "BGPERF_NOTIFY_CMD failed (exit $channel_status), so the operator was NOT told:" >&2
  echo "  $BGPERF_NOTIFY_CMD" >&2
  exit 1
fi

if [[ $CHECK -eq 1 ]]; then
  echo "notification channel delivered a test message"
fi
