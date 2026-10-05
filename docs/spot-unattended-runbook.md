# Unattended runs on spot: the operator's runbook

What you do, and what happens without you, when the 2026 daemon comparison runs
on EC2 spot. Set up on 2026-10-05. The decisions and their reasons are in
`docs/2026-daemon-comparison-plan.md` §9 ("Operator decisions, 2026-10-05, on
running the rest unattended on spot"). This page is only the how.

## Starting work

1. Launch an **`m7a.8xlarge`** with `ec2m`, spot is fine. Nothing else is needed.
2. Your phone gets an alert within a few minutes. "Wrong host" means ec2m gave
   you another type; the instance stays up and runs nothing.

Alerts go to the ntfy app, topic **`bgperf2-3syzalcle42fae3mo3flhgn4`**. You can
also open `https://ntfy.sh/bgperf2-3syzalcle42fae3mo3flhgn4` in a browser.
ntfy keeps messages about 12 hours.

## What runs by itself

`ec2m` runs `/data/on-launch.sh` at every launch. That starts
`scripts/spot_boot.sh`, which:

- runs the configs listed in `/data/bgperf-work/unattended/comparison-queue`,
  first line first, resuming a step where it stopped;
- stops between rows on a spot notice, so a reclaim costs at most one row;
- after each finished step, starts one headless Claude session that records
  it in the plan, commits on branch **`unattended/comparison`** (never master),
  and takes the step off the queue;
- alerts you on every outcome.

## The alerts, and what to do

| alert says | what it means | what you do |
|---|---|---|
| wrong host | not an m7a.8xlarge | relaunch as one, or use the box for other work |
| stopped at a cell boundary (spot notice) | reclaimed mid-step | nothing; the next launch resumes it |
| recorded on unattended/comparison | a step is recorded | nothing; merge when convenient (below) |
| **still waiting on you** / **a decision is needed** | a headless session hit a decision that is yours | read the alert and the plan, decide, then delete `/data/bgperf-work/unattended/status`. **Nothing runs until you do.** |
| session ... failed | the recording session broke | read the log the alert names; delete the status file to retry |
| queue is empty | nothing left to run | stop the instance |
| diverged from master | the branch has commits master lacks | merge it into master |

To decide something with Claude's help, open a session and say
`continue the 2026 daemon comparison`.

## Where things are

- Driver logs: `/data/bgperf-work/logs/spot-boot-*.log`; batch logs beside them.
- Queue and status: `/data/bgperf-work/unattended/`.
- Alert channel: `/data/bgperf-work/unattended.env` (holds the topic name; not in git).
- Results: `results/2026/2026-comparison/<step>/`.

## Merging the unattended work

```bash
git -C /data/bgperf2 checkout master
git -C /data/bgperf2 merge --ff-only unattended/comparison
```

Do it when nothing is running (`pgrep -af spot_boot.sh` prints nothing). The
next launch switches back to `unattended/comparison` and picks up master.

## Running by hand

- One step, on the right host: `scripts/run_comparison_step.sh [CONFIG]`. It
  refuses the wrong hardware and always resumes; never run the bare
  `bgperf2.py batch` command, which without `--resume` deletes a step's progress.
- The whole driver: `scripts/spot_boot.sh` (it logs to the file above, not the
  terminal).
- Summarise a finished step: `venv/bin/python scripts/comparison_step_table.py results/2026/2026-comparison/<step>`.

## Turning it off

Remove or rename `/data/on-launch.sh`, or empty the queue. Either is enough.
