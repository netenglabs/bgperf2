# Running bgperf2 on AWS EC2 (spot)

A setup for running benchmarks on cheap spot instances that you throw away between sessions
and recreate in a couple of minutes, with the built daemon images, the venv, and the MRT
files intact.

The expensive thing to preserve is `prepare`'s output — a pile of `bgperf/*` images compiled
from source. Everything here exists to keep that off the instance's own lifecycle.

Region assumed below is **us-east-2 (Ohio)**, which has good AMD capacity and where all the
prices quoted were checked (August 2026, on-demand and spot both move — re-check before
committing).

* [Why a separate data volume](#why-a-separate-data-volume)
* [Choosing an instance](#choosing-an-instance)
* [One-time setup](#one-time-setup)
* [The run cycle](#the-run-cycle)
* [Surviving interruptions](#surviving-interruptions)
* [What it costs](#what-it-costs)
* [Gotchas](#gotchas)

## Why a separate data volume

With on-demand instances you would not need one: an EBS-backed instance keeps its root
volume across `stop`/`start`, so you could stop the instance and start it again with
everything in place. Spot breaks that in three specific ways.

You *can* stop and start a spot instance yourself, but only if it came from a **persistent**
spot request (not one-time, not part of a fleet, launch group, or AZ group). Even then:

* **You cannot change the instance type while it is stopped.** AWS is explicit: "While a Spot
  Instance is stopped, you can modify some of its instance attributes, but not the instance
  type." That kills the resize-between-benchmarks workflow, which is most of the value of
  keeping one long-lived instance.
* **Cancelling the spot request terminates any stopped instance attached to it** — and with
  it, the root volume. One `cancel-spot-instance-requests` and `prepare` has to run again.
* **If EC2 interrupts you, only EC2 can restart the instance**, when capacity returns in the
  same AZ for the same instance type. You are not in control of when it comes back.

So instead: **keep everything valuable on a second EBS volume, and treat instances as
disposable.** The data volume holds the Docker image store, the repo, the venv, the MRT
files, and results. Any spot instance of any size can attach it. Resizing stops being an
instance operation and becomes "launch a different one."

This also removes the reason to fear interruption. Nothing on the root volume matters.

**One real constraint this introduces:** an EBS volume lives in a single Availability Zone,
so the data volume pins every launch to that AZ, and spot capacity is per-AZ. If your AZ goes
dry for the type you want, snapshot the volume and restore it into another AZ.

## Choosing an instance

The family letter is a RAM-per-vCPU ratio: `c` is 2 GB per vCPU, `m` is 4, `r` is 8. The
trailing letter is the vendor — `i` Intel, `a` AMD, `g` Graviton.

**Use AMD (`*a`).** On the `7a`/`8a` generations, SMT is off — AWS states "Each vCPU on M8a
and M8azn instances is a physical CPU core," versus Intel where two vCPUs share one core.
Same vCPU count, roughly double the real compute. That matters twice here: your baseline runs
were CPU-starved (below), and SMT sibling contention between the target daemon and the tester
containers is exactly the kind of noise that makes timing results irreproducible.

**Not Graviton (`*g`).** It is arm64; the daemon images build amd64 and cEOS/cRPD ship
amd64-only.

**Not burstable (`t3`, `t4g`).** CPU credits run out partway through a batch and throttle you
silently, which corrupts results rather than failing them. Spot itself is fine — it is
identical hardware with no throttling, so it costs you availability, never measurement
validity.

### What the measurements say

`benchmarks/baseline/baseline-benchmark.csv` is a 51-run matrix (10–100 neighbors ×
20k–100k prefixes, five targets) from 2025-06-06 on a 32-core / 60.74 GB host. Two findings
drive sizing.

**Host memory is not the target's memory:**

| Run | target `max mem` | host used (of 60.74 GB) |
|---|---|---|
| `bird` 100 × 50k | 0.62 GB | **43.1 GB** |
| `frr 9` 100 × 100k | 25.3 GB | **46.5 GB** |
| `frr 10` 100 × 100k | 8.97 GB | 31.2 GB |

BIRD holds its table in 0.62 GB while the host loses 43 GB — that is ~100 BIRD *tester*
containers plus the GoBGP monitor. Host memory tracks **peer count**, not how fat the daemon
under test is. (`min free mem` is really `free -m`'s *available* column — the regex in
`controller_memory_free()` captures the last field — so it reflects genuine pressure, not
page cache.)

**Several runs ran out of CPU before memory:**

```
rustybgp  100 x 50000   maxcpu 2037%   min_idle  0%   min_free 25.1 GB
frr 9     100 x 100000  maxcpu  117%   min_idle  0%   min_free 14.3 GB
```

RustyBGP is multithreaded and took 20 of 32 logical CPUs on its own while 25 GB sat free;
FRR and BIRD are single-threaded (~100–120%), so their CPU pressure is the testers. Note
`get_hardware_info()` uses `os.cpu_count()`, so that "32 cores" was 32 *logical* CPUs —
probably 16 physical. A 32-vCPU AMD instance roughly doubles the real compute.

A run that reaches `min_idle 0%` has testers competing with the target for CPU and measures
host contention as much as daemon performance.

### Spot prices and interruption rates, us-east-2

| Instance | cores | RAM | on-demand | spot from | disruption |
|---|---|---|---|---|---|
| `m7a.8xlarge` | 32 | 128 GB | $1.8547 | **$0.4222** (77%) | 5–10% |
| `m8a.8xlarge` | 32 | 128 GB | $1.9475 | $0.5702 (71%) | **>20%** |
| `r8a.8xlarge` | 32 | 256 GB | $2.5562 | $0.8414 (67%) | **<5%** |
| `r8a.12xlarge` | 48 | 384 GB | $3.8342 | **$1.1303** (71%) | **<5%** |

Two things fall out of this that are not obvious:

**The newest general-purpose type is the worst spot bet.** `m8a.8xlarge` carries a >20%
disruption rate in us-east-2 — high demand, thin spot pool. `m7a.8xlarge` is both cheaper and
more stable.

**On spot, the m-vs-r tradeoff inverts.** On-demand, `r` costs a large premium for memory you
may not need, which is why `m` is the right on-demand answer for this matrix. On spot the
`r8a` pool is quiet enough that the discount is deeper *and* the interruption rate is four
times better. `r8a.12xlarge` at $1.13/hr spot — 48 physical cores and 384 GB — costs less
than `m7i.8xlarge` on-demand ($1.61/hr) with half the real cores and a third of the memory.

### Recommendations

| Workload | Instance | cores / RAM | spot |
|---|---|---|---|
| Smoke test (`bench -t bird -n1 -p1`) | `c7a.xlarge` | 4 / 8 GB | ~$0.04 |
| `bench.yaml`, `bench-bird.yaml` — cheapest | `m7a.8xlarge` | 32 / 128 GB | $0.42 |
| …same, if interruptions annoy you | `r8a.8xlarge` | 32 / 256 GB | $0.84 |
| `benchmark.yaml` — MRT full table | `r8a.8xlarge` | 32 / 256 GB | $0.84 |
| `big-tests.yaml` — 1000+ neighbor sweeps | `r8a.12xlarge` | 48 / 384 GB | $1.13 |

The baseline matrix peaked at 46.5 GB used and 0% idle, so 128 GB with 32 real cores clears
it with room; 256 GB clears it comfortably. `r8a.12xlarge`'s 384 GB matches the note in
`big-tests.yaml` exactly:

```
# with 384 GB RAM, can't do more than 1000n at 1000p
```

Bid the on-demand price as your max (the default). You then only ever get interrupted for
capacity, never for price, while still paying the market rate.

### Then correct it from your own run

Do not trust the table past the first run. The CSV already logs what you need:

* **`min free mem` below ~20% of total** → more memory.
* **`min idle%` approaching 0** → more cores, *and treat those rows as suspect*.
* **`max cpu %` well above 100%** → that target is multithreaded (RustyBGP) and will absorb
  every core you give it.

Then launch a different instance against the same data volume.

## One-time setup

### 1. Create the data volume

Size it for the Docker image store (`prepare` compiles ~8 daemons into separate images,
including three FRR variants), the uncompressed MRT file, the repo and venv, and results.
**200 GB gp3.**

```bash
aws ec2 create-volume --region us-east-2 --availability-zone us-east-2b \
  --size 200 --volume-type gp3 --throughput 250 \
  --tag-specifications 'ResourceType=volume,Tags=[{Key=Name,Value=bgperf2-data}]'
```

Note the AZ you pick — every later launch must be in it.

### 2. Launch the first spot instance

Ubuntu 24.04 LTS, x86_64, small root volume (30 GB is plenty — nothing lives there), in the
data volume's AZ. Attach an IAM instance profile with `AmazonSSMManagedInstanceCore` so you
can connect via Session Manager and never care about the changing public IP.

```bash
aws ec2 run-instances --region us-east-2 \
  --image-id <ubuntu-24.04-amd64-ami> \
  --instance-type m7a.8xlarge \
  --instance-market-options 'MarketType=spot' \
  --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=30,VolumeType=gp3}' \
  --iam-instance-profile Name=<your-ssm-profile> \
  --placement AvailabilityZone=us-east-2b \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=bgperf2}]'
```

Then attach the data volume:

```bash
aws ec2 attach-volume --region us-east-2 \
  --volume-id vol-xxxxxxxx --instance-id i-xxxxxxxx --device /dev/sdf
```

### 3. Format the data volume — once, ever

> **This step destroys everything on the volume.** Run it on first setup only. On every later
> launch, skip straight to mounting. `mkfs` on a volume that already holds your images means
> running `prepare` again.

```bash
lsblk                                   # confirm the device, usually /dev/nvme1n1
sudo mkfs.ext4 /dev/nvme1n1             # FIRST TIME ONLY
sudo mkdir -p /data
sudo mount /dev/nvme1n1 /data
sudo chown ubuntu:ubuntu /data
```

### 4. Point Docker at the data volume

This is what makes the built images survive instance termination. Do it **before**
`prepare`, and before any image exists.

```bash
sudo apt update && sudo apt install -y docker.io
sudo systemctl stop docker
sudo mkdir -p /data/docker
echo '{"data-root": "/data/docker"}' | sudo tee /etc/docker/daemon.json
sudo systemctl start docker
docker info | grep "Docker Root Dir"    # should say /data/docker
```

### 5. Install bgperf2 on the data volume

```bash
git clone https://github.com/netenglabs/bgperf2.git /data/bgperf2
cd /data/bgperf2
./new_vm.sh
```

`new_vm.sh` handles the rest of the OS setup: `docker.io`, `python3-venv`, `sysstat` (for
`mpstat`, which `bench` shells out to), adds you to the `docker` group, creates the venv, and
downloads `mrt/rib.20210801.0000` from RouteViews in the background.

Log out and back in for the `docker` group, then:

```bash
cd /data/bgperf2
venv/bin/python bgperf2.py prepare   # slow — compiles every daemon from source
venv/bin/python bgperf2.py doctor    # confirm the bgperf/* images exist
```

This is the step the whole document exists to avoid repeating.

## The run cycle

Every subsequent session: launch, mount, run, terminate.

Put the per-launch work in user-data so it is automatic. Note there is **no `mkfs`** here:

```bash
#!/bin/bash
set -eux
apt-get update && apt-get install -y docker.io python3-venv sysstat
systemctl stop docker
mkdir -p /data
mount /dev/nvme1n1 /data
mkdir -p /data/docker
echo '{"data-root": "/data/docker"}' > /etc/docker/daemon.json
systemctl start docker
usermod -aG docker ubuntu
echo 'net.ipv4.neigh.default.gc_thresh3 = 16384' > /etc/sysctl.d/99-bgperf.conf
sysctl --system
```

That `gc_thresh3` bump is needed for more than 1024 neighbors, per the note in
`big-tests.yaml`. It has to be re-applied on every launch, which is why it belongs here
rather than in a file on the root volume.

Then run, and when finished:

```bash
aws ec2 terminate-instances --region us-east-2 --instance-ids i-xxxxxxxx
```

The data volume detaches cleanly and waits for the next launch. To use a different size next
time, just pass a different `--instance-type`; nothing about the volume changes.

**Do not compare results across instance types.** Different families and core counts produce
different absolute numbers, and bgperf2 does not record which instance you used — only
`cores` and `Mem (GB)`. Keep every run in a comparison set on one type, and note the type
alongside the CSV.

### A dead-man switch

Spot is cheap, not free, and an `r8a.12xlarge` left running all weekend is still real money.
Either bound the session from inside:

```bash
sudo shutdown -h +240
```

or attach a CloudWatch alarm on `CPUUtilization < 5%` for 30 minutes with a terminate action.

## Surviving interruptions

Spot gives you a two-minute warning and takes the instance. Three things make that cheap
here:

**Results are already incremental.** `batch()` rewrites the test's CSV after *every*
`bench()` call — the loop carries the comment "update this each time in case something
crashes" — so an interruption costs you the single run in flight, not the matrix. With
`results_dir` on `/data`, everything finished is already durable.

**Nothing else is on the instance.** Images, repo, venv, MRT files all live on the data
volume. Recovery is: launch another instance, mount, re-run the last cell.

**Pick your pool deliberately.** The disruption column above is the whole game: `r8a` at <5%
will usually carry a multi-hour batch to completion; `m8a` at >20% probably will not. If a
batch matters, spend the extra $0.40/hr.

If you would rather have AWS pause and resume you, launch from a **persistent** spot request
with `--instance-interruption-behavior stop`. EC2 then stops rather than terminates on
interruption, preserves the volumes, and restarts when capacity returns — but only EC2
decides when, and you give up the ability to change instance type. Given the data volume
already makes instances disposable, plain one-time spot requests plus relaunch is simpler.

## What it costs

Between sessions you pay for the data volume and nothing else: gp3 at about $0.08/GB-month,
so 200 GB is roughly **$16/month** to keep a fully-built bgperf2 environment on standby. The
30 GB root volume dies with the instance.

While running, the spot column above: $0.42/hr for the baseline matrix on `m7a.8xlarge`,
$1.13/hr for the big sweeps on `r8a.12xlarge`. Do not allocate an Elastic IP — it bills even
when idle, and SSM makes it unnecessary.

## Gotchas

**`mkfs` is the one irreversible step.** It appears once in this document for a reason. If a
launch script ever runs it unconditionally, the first interruption costs you `prepare`.
Snapshot the volume after a successful `prepare` as insurance:

```bash
aws ec2 create-snapshot --region us-east-2 --volume-id vol-xxxxxxxx \
  --description "bgperf2 after prepare"
```

**Docker `data-root` must be set before the first image is built.** Change it afterwards and
Docker silently starts from an empty store on the new path, leaving the old images stranded
on the root volume — which then dies with the instance.

**The volume pins you to one AZ.** Spot capacity varies per AZ, so a bad AZ for your chosen
type means either a different type or a snapshot-and-restore into another AZ.

**Root-owned files in `/tmp/bgperf2`.** The commercial NOS targets (cRPD, cEOS, SR Linux)
write files there as root that bgperf2 cannot clean up. On this setup `/tmp` is on the
ephemeral root volume, so termination clears them for free — but within a session,
`sudo rm -rf /tmp/bgperf2` if a run fails oddly.

**The venv is tied to its interpreter.** `new_vm.sh` runs `apt upgrade`, and a distro Python
upgrade orphans the venv on the data volume — it will outlive the instance that created it,
so this bites eventually. Symptoms are import errors on a setup that worked last session:

```bash
cd /data/bgperf2 && rm -rf venv && python3 -m venv venv && venv/bin/pip install -r pip-requirements.txt
```

**`build_bgperf.sh` builds every daemon image in parallel**, which is much faster than
`prepare` on a fresh instance since `prepare` builds them one at a time.

**Commercial NOS images are never built by `prepare`.** Download cRPD, cEOS, and SR Linux out
of band and `docker load` them under the exact tags bgperf2 looks up (`crpd:latest`,
`ceos:latest`); anything else fails confusingly. They land in `/data/docker` with everything
else, so they only need loading once. Their licenses prohibit publishing results.

**Back up results you care about.** They are on one EBS volume with no redundancy:

```bash
aws s3 sync /data/bgperf2/results/ s3://your-bucket/bgperf2-results/
```

## Sources

* [Behavior of Spot Instance interruptions](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/interruption-behavior.html) — stop-on-interruption requirements, no instance-type change while stopped
* [EC2 Spot instances can now be stopped and started similar to On-Demand instances](https://aws.amazon.com/about-aws/whats-new/2020/01/amazon-ec2-spot-instances-stopped-started-similar-to-on-demand-instances)
* [Amazon EC2 M8a Instances](https://aws.amazon.com/ec2/instance-types/m8a/) — "Each vCPU on M8a and M8azn instances is a physical CPU core"
* [New General Purpose Amazon EC2 M8a Instances](https://aws.amazon.com/about-aws/whats-new/2025/10/general-purpose-amazon-ec2-m8a-instances/) — launch regions
* [Announcing New EC2 R8a Memory-Optimized Instances](https://aws.amazon.com/about-aws/whats-new/2025/11/memory-optimized-amazon-ec2-r8a-instances/)
* Spot prices and disruption bands: [DoiT Compute](https://www.doit.com/compute/spot/us-east-2/r8a.12xlarge), checked August 2026
