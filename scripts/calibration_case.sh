#!/usr/bin/env bash
#
# Produce a Phase 6 calibration case on demand, by starving one role.
#
# The measurement plan asks for controlled calibration cases: a run whose
# bottleneck was chosen in advance, so the findings policy can be checked
# against a known cause rather than against whatever the host happened to be
# doing.  The controlled confounder (a two-core foreign load started outside
# bgperf2's process tree) was the first.  This produces the other two:
#
#   a slow tester          the generators are still delivering when the run
#                          ends, and it should be attributed to `tester` via
#                          `tester_limited`.
#   a target/observer tail the run continues after the generators finish, and
#                          it should be attributed to `target_or_monitor` via
#                          `post_injection_tail`.
#
# The roles are bgperf2's own three, and the tail case is reachable from
# either end of that name: a starved target and a starved monitor both leave
# the run running after the generators are done, and the finding is called
# `target_or_monitor` precisely because no interval here separates them.
#
# Two knobs, because the two roles are held up by different resources and
# using the wrong one produces a case that is not controlled at all.  Measured
# here on 2026-09-08: bgpdump2 injectors capped at 0.2 CPU took 6.3s and 8.3s
# to become ready against 1.3s and 2.3s unconstrained, and then walked their
# tables in 0.833s against 0.867s -- reading the MRT file is CPU-bound, and the
# walk is spent blocked on socket writes.
# A target's route processing is CPU-bound and does respond to --cpus.
#
#   --cpus N   `docker update --cpus` on each of the role's containers.
#   --rate R   a tbf qdisc at rate R on every device inside each of the
#              role's own network namespaces, so it is that container's
#              *egress* that is capped -- what a generator can send, not what
#              it can be sent.
#
# The constraint is applied from outside bgperf2, for the same reason the
# foreign load was started outside its process tree: nothing here changes what
# the instrument measures, only what there is to measure.  bgperf2 is not told
# and does not record it -- provenance never guesses, and a run's manifest may
# not claim a constraint the tool did not apply.  The record is this script's
# own log lines and the decision log entry that cites them.
#
# Usage:
#   scripts/calibration_case.sh --role tester --rate 10mbit -- \
#       -d /data/bgperf-work bench -t bird --version 3.3.2 ...
#
# Everything after `--` is passed to bgperf2.py verbatim, top-level options
# included -- `-d` is one of those and belongs before the subcommand.

set -u -o pipefail

usage() {
    cat >&2 <<'USAGE'
usage: scripts/calibration_case.sh --role tester|target|monitor
                                   [--cpus N] [--rate R]
                                   -- <bgperf2 args...>

  --role tester   constrain every generator container (bgperf_*_tester_*)
  --role target   constrain the target container (bgperf_*_target)
  --role monitor  constrain the monitor container (bgperf_monitor)
  --cpus N        CPU limit applied to each of those containers
  --rate R        egress rate limit applied inside each of them (needs sudo)

At least one of --cpus and --rate is required.  Containers are matched by the
naming convention CLAUDE.md states rather than by a copy of any class
attribute, and the script fails if it constrained nothing: a case that quietly
applied no constraint is not a controlled case.
USAGE
    exit 2
}

role=
cpus=
rate=
while [ $# -gt 0 ]; do
    case "$1" in
        --role) role=${2:-}; shift 2 || usage ;;
        --cpus) cpus=${2:-}; shift 2 || usage ;;
        --rate) rate=${2:-}; shift 2 || usage ;;
        --) shift; break ;;
        *) usage ;;
    esac
done

[ -n "$role" ] && [ $# -gt 0 ] || usage
[ -n "$cpus" ] || [ -n "$rate" ] || usage

case "$role" in
    # `.*tester_`, not `_tester_`: the MRT injectors are
    # `bgperf_exabgp_mrttester_` and `bgperf_gobgp_mrttester_`, which have no
    # underscore before "tester" and were silently matched by nothing.
    tester) pattern='bgperf_.*tester_' ;;
    target) pattern='bgperf_.*_target$' ;;
    monitor) pattern='bgperf_monitor$' ;;
    *) usage ;;
esac

here=$(cd "$(dirname "$0")/.." && pwd)
log=$(mktemp "${TMPDIR:-/tmp}/calibration_case.XXXXXX")

# The venv is how CLAUDE.md says to run this, and an unactivated shell reaches
# bgperf2.py's imports and dies there -- which the guard below would then
# report as "no container was constrained", blaming the case for a missing
# interpreter.
python=$here/venv/bin/python
[ -x "$python" ] || python=python3

if [ -n "$rate" ] && ! sudo -n true 2>/dev/null; then
    echo "--rate needs passwordless sudo to enter the container's netns" >&2
    exit 2
fi

declare -A container_pid
declare -A limited_cpu
declare -A limited_rate
declare -A limited_dev
declare -A settled
declare -A attempts
declare -A finished

# How many consecutive passes a container has to come back fully constrained
# before this stops looking at it.  Bounded on purpose: re-reading a device
# list forever costs a `sudo nsenter ip` per container per pass for the whole
# run, and the watcher is a *sibling* of bgperf2 rather than a descendant, so
# `contention.own_process_tree()` cannot exclude it and none of `sudo`,
# `nsenter` or `ip` is in `BGPERF_PROCESSES`.  At ten injectors that is ~100
# short-lived processes a second charged to `max foreign cpu %` -- and past
# `CONTENTION_PERCENT` the findings policy withholds the verdict, so the
# instrument would suppress the very case it was built to produce.
DEVICE_SETTLED_PASSES=3

# And how many passes a container gets before its constraint is given up on.
# A `docker update` or a `tc` that has failed this many times is not about to
# start working -- an unsupported quota, a sudo credential that expired
# mid-batch, a container in a bad state -- and retrying at 10 Hz for the rest
# of the run is the same load, spent on nothing.  Giving up is safe *because*
# the guard at the end counts containers rather than successes: a container
# abandoned here fails the run instead of passing quietly.
MAX_ATTEMPTS=50

note() {
    printf '%s constrained %s to %s\n' "$(date -Is)" "$1" "$2" >>"$log"
}

# A container's own network namespace, minus loopback.  Every device, not
# eth0: a bgperf2 container is on two networks and which of eth0/eth1 carries
# BGP is not fixed.  Shaping eth0 alone was measured constraining one injector
# of two in one run and neither in the next, and both runs reported the
# constraint as applied, because the tc command had succeeded -- a case that
# binds no traffic is the failure this whole script exists to make impossible.
devices() {
    sudo -n nsenter -t "$1" -n ip -o link 2>/dev/null \
        | awk -F': ' '{split($2, a, "@"); if (a[1] != "lo") print a[1]}'
}

# The rate knob, for one container: every device it has, or it does not count.
# A `tc` that fails is *not* a settled device set -- treating "nothing left to
# add" as success would let a container whose every `tc` failed be marked done
# and run at line rate for the whole run while the others were shaped.
shape_devices() {
    local id=$1 name=$2 pid=$3 dev= total=0 shaped=0
    for dev in $(devices "$pid"); do
        total=$((total + 1))
        if [ -n "${limited_dev[$id/$dev]:-}" ]; then
            shaped=$((shaped + 1))
        elif sudo -n nsenter -t "$pid" -n tc qdisc replace dev "$dev" root \
                tbf rate "$rate" burst 32kb latency 400ms >/dev/null 2>&1; then
            limited_dev[$id/$dev]=1
            shaped=$((shaped + 1))
            note "$name" "$rate egress on $dev"
        fi
    done
    [ "$total" -gt 0 ] && [ "$shaped" = "$total" ]
}

constrain() {
    local id=$1 name=$2 pid= want=0 got=0

    # Not this run's container.  bgperf2 removes and recreates anything it
    # finds by name, so a constraint applied to a leftover is thrown away
    # seconds later -- while a guard counting successes would take it for a
    # controlled case.  Review demonstrated exactly that, and it is the normal
    # state of this machine: a bench leaves its testers and monitor running.
    case "$preexisting" in *" $id "*) return 0 ;; esac

    if [ -z "${finished[$id]:-}" ]; then
        echo "$id" >>"$log.seen"
        finished[$id]=no
    fi
    [ "${finished[$id]}" = no ] || return 0

    if [ "${attempts[$id]:-0}" -ge "$MAX_ATTEMPTS" ]; then
        finished[$id]=gave-up
        return 0
    fi
    attempts[$id]=$(( ${attempts[$id]:-0} + 1 ))

    if [ -n "$cpus" ]; then
        want=$((want + 1))
        if [ -n "${limited_cpu[$id]:-}" ]; then
            got=$((got + 1))
        elif docker update --cpus="$cpus" "$id" >/dev/null 2>&1; then
            limited_cpu[$id]=1
            got=$((got + 1))
            echo "$id" >>"$log.cpu"
            note "$name" "$cpus CPU"
        fi
    fi

    if [ -n "$rate" ]; then
        want=$((want + 1))
        pid=${container_pid[$id]:-}
        if [ -z "$pid" ]; then
            pid=$(docker inspect -f '{{.State.Pid}}' "$id" 2>/dev/null) || pid=
        fi
        if [ -n "$pid" ] && [ "$pid" != 0 ]; then
            container_pid[$id]=$pid
            # Re-enumerated on every pass until this container is finished,
            # never short-circuited on "it was fully shaped once". Skipping the
            # re-read is what made the settling passes below a no-op: a device
            # attached after the first fully-shaped pass would never be shaped,
            # and the run would still be reported as controlled -- which is the
            # partial-shaping failure this script exists to make impossible,
            # arrived at from a third direction. `limited_dev` still keeps it
            # from re-issuing `tc` for a device already done.
            if shape_devices "$id" "$name" "$pid"; then
                got=$((got + 1))
                if [ -z "${limited_rate[$id]:-}" ]; then
                    limited_rate[$id]=1
                    echo "$id" >>"$log.rate"
                fi
            fi
        fi
    fi

    # Fully constrained for a few passes running, so a device attached after
    # the container starts is still caught; anything short of that restarts
    # the count and keeps the container in the scan.
    if [ "$got" = "$want" ]; then
        settled[$id]=$(( ${settled[$id]:-0} + 1 ))
        [ "${settled[$id]}" -lt "$DEVICE_SETTLED_PASSES" ] \
            || finished[$id]=ok
    else
        settled[$id]=0
    fi
}

# Keyed on container id, not name: bgperf2 removes and recreates a container
# under the same name within one run, and a watcher reading names alone would
# take the second one for the first and leave it unconstrained.
watch_loop() {
    while :; do
        while read -r id name; do
            [ -n "$id" ] || continue
            constrain "$id" "$name"
        done < <(docker ps --format '{{.ID}} {{.Names}}' \
                 | grep -E " $pattern" || true)
        # Fast enough that the constraint lands before the role does the work
        # being constrained: a bgpdump2 injector starts its walk as soon as it
        # has read its MRT file, and a constraint applied after that would be
        # recorded as applied while an unconstrained send was measured.
        sleep 0.1
    done
}

# Snapshot before anything starts, so `constrain()` can tell this run's
# containers from an earlier run's leftovers.  Reported rather than silently
# skipped: on this host a bench that outlived itself is a known hazard, and it
# competes with the run about to start (CLAUDE.md, host contention).
preexisting=" $(docker ps --format '{{.ID}} {{.Names}}' \
                | grep -E " $pattern" | awk '{print $1}' | tr '\n' ' ')"
if [ -n "${preexisting// /}" ]; then
    echo "note: ignoring $role containers left over from an earlier run;" >&2
    echo "      they are not this run's and bgperf2 will remove them." >&2
fi

watch_loop &
watcher=$!
trap 'kill "$watcher" 2>/dev/null' EXIT INT TERM

echo "calibration case: $role limited to ${cpus:+$cpus CPU}${cpus:+${rate:+, }}${rate:+$rate egress}" >&2
"$python" "$here/bgperf2.py" "$@"
status=$?

kill "$watcher" 2>/dev/null
trap - EXIT INT TERM

echo >&2

# Counted per container, not "something was constrained".  A single marker
# per knob cannot tell one constrained injector from ten, or the first batch
# cell from all forty: one success would satisfy it while the other nine
# generators, or the remaining thirty-nine cells, ran unconstrained.
count() { sort -u "$1" 2>/dev/null | grep -c . || true; }

seen=$(count "$log.seen")
unapplied=
if [ -n "$cpus" ]; then
    applied=$(count "$log.cpu")
    [ "$applied" = "$seen" ] || unapplied="--cpus ($applied of $seen)"
fi
if [ -n "$rate" ]; then
    applied=$(count "$log.rate")
    [ "$applied" = "$seen" ] \
        || unapplied="${unapplied:+$unapplied, }--rate ($applied of $seen)"
fi

if [ "$seen" = 0 ] || [ -n "$unapplied" ]; then
    if [ "$seen" = 0 ]; then
        echo "FAILED: no $role container of this run was seen at all." >&2
    else
        echo "FAILED: $role containers of this run went unconstrained by:" \
            "$unapplied" >&2
    fi
    echo "This run is not a controlled case and its findings say nothing" >&2
    echo "about $role." >&2
    [ -s "$log" ] && { echo "what did apply:" >&2; cat "$log" >&2; }
    rm -f "$log" "$log".seen "$log".cpu "$log".rate
    exit 1
fi

echo "all $seen $role container(s) of this run were constrained:" >&2
cat "$log" >&2
rm -f "$log" "$log".seen "$log".cpu "$log".rate
exit "$status"
