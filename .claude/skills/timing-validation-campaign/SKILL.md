---
name: timing-validation-campaign
description: Run, monitor, resume or accept exactly one block of the 64 GB timing validation campaign (run ID 2026-timing-validation). Use when the user says "continue the 64 GB timing validation campaign", or asks about timing-validation blocks, their RAN/COMPLETE markers, or scripts/run_timing_validation_block.sh.
---

# 64 GB timing validation campaign operator contract

When the user says `continue the 64 GB timing validation campaign`, follow
`docs/2026-64gb-timing-validation-plan.md` with run ID
`2026-timing-validation`, results root `results/2026`, and work directory `/data/bgperf-work`. Verify the measurement
release gate first. Never run cells or blocks concurrently. Monitor or resume an active block; otherwise run exactly
one next block, review timing evidence, correctness, provenance, contention, and memory, then stop at the reviewed
block boundary. The local 64 GB host is a hard ceiling; do not schedule a larger-memory workload.

**The entry point is `scripts/run_timing_validation_block.sh`** (`status`, `next`,
`accept N --note "..."`), which carries that identity as its defaults and holds a lock so two blocks
cannot run at once. It writes **two** markers: `RAN` when a block's mechanical work finished, and
`COMPLETE` only when an operator accepts it after review -- `next` advances past `COMPLETE` alone.
That split is what makes "stop at the reviewed block boundary" durable rather than a habit: a
session that died between the batch and the review would otherwise leave a block indistinguishable
from a reviewed one. A block whose configs and procedure have not been written yet exits 2 saying
so rather than improvising a matrix, and every benchmark block runs
`scripts/check_timing_evidence.py` over its own results before it claims to have run -- that is the
plan's Acceptance Rules as code, reading the published documents and re-deriving no measurement.

**`RAN` states that the work ran, not that it qualified**, and that distinction is what keeps a
block with one bad row from becoming unreachable. Written only on the passing path -- as it was --
a single rejected row could be neither accepted nor re-measured: `accept` refuses a block with no
`RAN`, and `next`, seeing a directory and no marker, re-selected the block and ran it with
`--resume`, which skips every cell the progress file already holds *including the failed ones*
(`batch()` records `completed[cell_id] = bench(a)` for a FAILED run exactly as for a converged
one). The block re-ran, measured nothing, exited 0, and failed the identical check; the cell that
most needed re-measuring was the one resume would never re-run. So the marker carries the verdict
beside the fact, and what the verdict controls is the exit status and what `accept` demands.

**A block that stopped mid-run is `interrupted`, not unfinished.** The
campaign host is a spot instance; a reclaim stops the block at a cell boundary
with every measured cell checkpointed, and `RAN` records what the run itself
said (`stopped: <reason>`, verbatim -- any SIGTERM reaches the same path, so
the marker claims no cause). Continue it with `block-N --resume-after-stop`,
which keeps those cells and measures only what never ran -- never `--force`,
which is the opposite flag and discards them (the two are refused together).
The resume is itself refused for a block whose `RAN` records no stop, because
over an ordinary failure it would skip the failed cells and re-stamp their
rows. A resumed block spans two hosts by construction, which the host rule
above already allows: `resumed_after_stop: yes` in `RAN`, the per-attempt
detail in the manifest's `previous_entries`, and the split named in the block's
record. A marker written before the runner learned to record the stop carries
the shortfall without it, and `record-stop N` is the migration for exactly
that: it copies the reason verbatim out of that block's own run logs, refuses
when no log carries one, and marks what it wrote `stopped_backfilled:`. It was
run once, on Block 10.

**A rejected row is accepted only as an explicit exclusion**: `accept N --with-exclusions --note
"why"`, which is the plan's "14 reviewed rows *or* explicit durable exclusions with evidence"
written where a later session can still read it. The marker names the rows, from the verdicts
themselves rather than from a count of failed checker calls -- Blocks 2-7 make one call covering 14
runs, so that count is 1 whether one row was rejected or all of them. **A missing run is not an
exclusion.** `check_timing_evidence.py` also exits non-zero on a shortfall, and a block that
produced 9 artifacts for 14 configurations is unfinished work rather than a result to exclude; the
two are reported apart (`excluded_row:` against `missing_runs:`), on the same rule `summary.py` and
`findings.py` follow everywhere else. Re-measuring means `--force`, which discards that block's
previous results, artifacts, markers and batch progress -- there is no way to re-run a single cell.

**The campaign host is settled: the machine this repository is checked out on** -- 16 vCPU, 61.44
GiB, AMD EPYC 9R14 (`m7a.4xlarge`), resized into that shape on 2026-09-03. Justin chose it on
2026-09-08 as the closest available match to the host that produced
`benchmarks/baseline/baseline-benchmark.csv`, which is a match on memory (61.44 GiB against 60.74)
and **not** on CPU. Run Phase 6 calibration and every campaign block on a host of that class.

**"That machine" is a class, not a machine, because it is an EC2 spot instance and is reclaimed
without warning.** This said "one host for the whole experiment" until 2026-09-10, which was never
a rule the campaign could keep: by the time anyone read the manifest it had already recorded three
hostnames across blocks 0-2, and Block 2 was measured on two of them because a reclaim landed
between its cells. Do **not** read a two-host block as invalidating and re-measure it -- that
discards rows that qualified in order to satisfy a rule the hardware cannot honour. The rule is in
the timing plan's Fixed Campaign Identity and is summarised here: a replacement matching on
**instance type, CPU model, vCPU count and memory** continues the campaign; kernel, AZ and instance
ID are recorded and advisory; a host change *between* blocks is expected and recorded, and one
*within* a block is a finding stated in that block's record, not grounds to discard it. All of it
is checkable after the fact, per block, under `metadata/manifest.json` -- `blocks.<key>.host` for
the attempt that finished, `previous_entries` for the ones a reclaim interrupted and the rows each
measured. Checkable **from block 3 onward**: `host.instance` was added with the rule on 2026-09-10,
so blocks 0-2 record CPU, cores, memory and hostname and not the instance type the rule turns on. **Only `/data` survives a reclaim** (its own EBS volume, carrying the repo, `results/`,
Docker's `data-root` and `/home/ubuntu`); the root filesystem is fresh on every replacement, which
is the harder half of why the work directory is `/data/bgperf-work` and not `/var/tmp`.

The CPU cost against the 2025 baseline is paid in exactly one place:
**campaign rows may never be read against `benchmarks/baseline/baseline-benchmark.csv`**. That is
already the campaign's own design (it is not a continuation of `2026-baseline`, it re-runs the
comparisons under a new run identity), so nothing has to be given up for it -- but nothing refuses
it either, and `create_batch_graphs()` will put two hosts' bars side by side without comment.

**The work directory in the `2026-benchmark-campaign` contract and in this one moved to
`/data/bgperf-work` for this host**, and
that is the whole of the change -- there is no advisory version of it, because a work directory
named in prose beside a contract that pins a different one is read as decoration. `/var/tmp` here
is on the **29 GB root**, with ~26 GB free, shared with journald and the OS; `/data` has ~150 GB.
Docker itself is safe either way -- `/etc/docker/daemon.json` sets `data-root` to `/data/docker` on
this host, so images and container logs are not on the root. `2026-core-mrt.yaml` runs 14 target
configurations at 1.05M prefixes, five of them `frr_c` whose `bgpd.log` alone passes 1 GB, and
`warn_if_log_dir_is_short_on_space()` only fires below `LOG_SPACE_FLOOR_GB` (10) -- so a batch can
fill the root hours in and take Docker and journald down with it, losing the *finished* cells'
artifacts rather than the current run. The `2026-baseline` contract's "unless durable run metadata
already records different values" clause still wins for that campaign, so anything in flight keeps
the directory it recorded. **The timing-validation campaign has no such clause** -- its work
directory is part of Fixed Campaign Identity -- but it has not started, so there is nothing to
contradict; if a block is ever found mid-flight against `/var/tmp/bgperf`, the recorded manifest
wins and the discrepancy is a finding to report, not a path to silently switch.

---

This contract used to live in `CLAUDE.md`. It moved here because it is triggered by an
exact user phrase, which is what a skill description is; the body is loaded in full on
invocation, so nothing about it has been condensed.
