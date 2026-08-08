# Running bgperf2 on AWS EC2

A setup for running benchmarks on an EC2 instance that you stop between sessions and bring
back in about a minute, with all the built daemon images, the venv, and the MRT files still
in place.

The whole idea rests on one fact: **the root EBS volume of an EBS-backed instance survives
`stop`/`start` automatically.** You do not need a separate data volume, an AMI, or any
sync step. The only rule is *stop, never terminate* — terminating deletes the root volume,
because `DeleteOnTermination` defaults to true on the root device.

* [Launch settings](#launch-settings)
* [Picking an instance size](#picking-an-instance-size)
* [First-time setup](#first-time-setup)
* [The stop/start cycle](#the-stopstart-cycle)
* [Resizing between benchmarks](#resizing-between-benchmarks)
* [What it costs while stopped](#what-it-costs-while-stopped)
* [Gotchas](#gotchas)

## Launch settings

| Setting | Value | Why |
|---|---|---|
| AMI | Ubuntu 24.04 LTS, **x86_64** | `new_vm.sh` is apt-based. Not Graviton — the daemon images build amd64, and cEOS/cRPD ship amd64 only |
| Instance type | `c7i` / `m7i` / `r7i` — see below | |
| Root volume | **gp3, 200 GB**, throughput raised to 250 MB/s | `prepare` compiles ~8 daemons into separate images and the MRT file is a couple GB uncompressed |
| Extra volumes | none | |
| IAM instance profile | one with `AmazonSSMManagedInstanceCore` | lets you connect without tracking a changing public IP |
| Public IP | not needed if you use SSM | since Feb 2024 every public IPv4 bills at $0.005/hr, attached or not |

The trailing letter is the CPU vendor: `i` Intel, `a` AMD, `g` Graviton. This doc names 7th
generation because it is available essentially everywhere; **8th-generation Intel (`m8i`,
`r8i`) is a drop-in upgrade with the same size ratios** — `r8i.12xlarge` is still 48 vCPU /
384 GB — so prefer it where your region offers it. Just don't mix generations within a set of
results you intend to compare.

Two things to **avoid**:

* **Burstable instances (`t3`, `t4g`).** They run at a baseline fraction of a vCPU and burn
  credits to exceed it. A long batch will exhaust its credits partway through and get
  throttled, which silently corrupts your numbers rather than failing — exactly the worst
  failure mode for a benchmark.
* **Instance-store NVMe (the `i7ie` family, or any `*d` type).** That storage is **wiped on
  stop**, which is precisely the thing this setup exists to avoid. If you do use such an
  instance, keep `/var/lib/docker` on the EBS root volume where it lands by default, and do
  not "helpfully" move it to the fast local disk.
* **Graviton (`m8g`, `r8g`, any `*g`).** It is arm64. The daemon images build amd64, and
  cEOS/cRPD ship amd64-only.

## Picking an instance size

The family letter is a RAM-per-vCPU ratio: `c` is 2 GB per vCPU, `m` is 4, `r` is 8. Choosing
between them is really the question *which resource runs out first*, and you should answer it
from measurements rather than from reasoning about BGP table sizes.

### What the measurements say

`benchmarks/baseline/baseline-benchmark.csv` is a 51-run matrix (10–100 neighbors ×
20k–100k prefixes, five targets) recorded on 2025-06-06 on a **32-core / 60.74 GB** host.
Every row logs `max mem`, `min free mem`, and `min idle%`, which is enough to size an
instance properly.

**Host memory is not the target's memory.** The two are nearly unrelated:

| Run | target `max mem` | host used (of 60.74 GB) |
|---|---|---|
| `bird` 100 × 50k | 0.62 GB | **43.1 GB** |
| `frr 8` 100 × 100k | 21.4 GB | 43.2 GB |
| `frr 9` 100 × 100k | 25.3 GB | **46.5 GB** |
| `frr 10` 100 × 100k | 8.97 GB | 31.2 GB |

BIRD holds the table in 0.62 GB while the host loses 43 GB — that is ~100 BIRD *tester*
containers plus the GoBGP monitor. **Host memory tracks peer count, not how fat the daemon
under test is.** Size for the testers; the target is often a rounding error.

(`min free mem` is really the *available* column of `free -m` — the regex in
`controller_memory_free()` captures the last field — so it reflects genuine pressure, not
page cache.)

**Several runs ran out of CPU before memory:**

```
rustybgp  100 x 50000   maxcpu 2037%   min_idle  0%   min_free 25.1 GB
frr 9     100 x 100000  maxcpu  117%   min_idle  0%   min_free 14.3 GB
```

RustyBGP is multithreaded and consumed 20 of the 32 cores on its own; FRR and BIRD are
single-threaded (~100–120%), so the CPU pressure in their runs comes from the testers. A run
that reaches `min_idle 0%` has the testers competing with the target for CPU, and measures
host contention as much as daemon performance.

### Recommendations

That matrix peaked at **46.5 GB used and 0% idle** on 32 cores / 60.74 GB — tight on both
axes. Hence `m` (4 GB/vCPU) rather than `r`: it roughly doubles the memory ratio of that
box without giving up cores that were also exhausted.

| Workload | Instance | vCPU / RAM |
|---|---|---|
| Quick smoke test (`bench -t bird -n1 -p1`) | `c7i.xlarge` | 4 / 8 GB |
| `bench.yaml`, `bench-bird.yaml` — the baseline matrix above | `m7i.8xlarge` | 32 / 128 GB |
| …same, with RustyBGP no longer host-bound | `m7i.12xlarge` | 48 / 192 GB |
| `benchmark.yaml` — MRT full table, 800k prefixes, 10 neighbors | `m7i.8xlarge` | 32 / 128 GB |
| `big-tests.yaml` — 1000+ neighbor sweeps | `r7i.12xlarge` | 48 / 384 GB |

`r` earns its place only at the `big-tests.yaml` end: 1000+ neighbors of single-threaded
BIRD or FRR, where path count climbs but the target cannot use extra cores. That is also
where the file's own note lands —

```
# with 384 GB RAM, can't do more than 1000n at 1000p
```

— and `r7i.12xlarge` is exactly 48 × 8 = 384 GB.

### Then correct it from your own run

Do not trust the table above past the first run. After any batch, read the columns the CSV
already gives you:

* **`min free mem` below ~20% of total** → go up in memory.
* **`min idle%` approaching 0** → go up in cores, *and treat those rows as suspect* — a
  CPU-starved tester makes the target look slow.
* **`max cpu %` well above 100%** → that target is multithreaded (RustyBGP) and will absorb
  every core you give it, unlike FRR and BIRD.

Then [resize](#resizing-between-benchmarks) and re-run. The instance type is a property you
change on a stopped instance, not something baked into the volume, so the cost of guessing
wrong is about two minutes.

If you intend to publish numbers and want to rule out hypervisor and noisy-neighbor effects
entirely, the `.metal` variants (`m7i.metal-24xl` and friends) give you the whole host. They
cost accordingly; for comparing daemons against each other on the same instance in the same
session, a normal shared-tenancy instance is fine.

## First-time setup

`new_vm.sh` in the repo root does the OS-level work: apt update/upgrade, `docker.io`,
`python3-venv`, `sysstat` (for `mpstat`, which `bench` shells out to), adds you to the
`docker` group, creates the venv, and downloads `mrt/rib.20210801.0000` from RouteViews in
the background.

```bash
git clone https://github.com/netenglabs/bgperf2.git
cd bgperf2
./new_vm.sh
sudo reboot                          # so the docker group applies
```

Then, back on the instance:

```bash
cd bgperf2
venv/bin/python bgperf2.py prepare   # slow — compiles every daemon from source
venv/bin/python bgperf2.py doctor    # confirm the bgperf/* images exist
```

`prepare` is the expensive step and the reason this whole document exists. Run it once; it
survives every subsequent stop/start.

### Kernel tuning that has to persist

`big-tests.yaml` notes that more than 1024 neighbors needs a larger ARP table. Put it in
`/etc/sysctl.d/` rather than echoing into `/proc`, so it survives reboots and restarts:

```bash
echo 'net.ipv4.neigh.default.gc_thresh3 = 16384' | sudo tee /etc/sysctl.d/99-bgperf.conf
sudo sysctl --system
```

### Optional: skip the manual steps with user-data

Paste this as user-data at launch and the instance bootstraps itself. It still leaves
`prepare` for you to run, since that takes long enough that you want to watch it.

```bash
#!/bin/bash
set -eux
echo 'net.ipv4.neigh.default.gc_thresh3 = 16384' > /etc/sysctl.d/99-bgperf.conf
sysctl --system
sudo -u ubuntu git clone https://github.com/netenglabs/bgperf2.git /home/ubuntu/bgperf2
cd /home/ubuntu/bgperf2
sudo -u ubuntu ./new_vm.sh
```

### Optional: a dead-man switch

An `r7i.12xlarge` left running over a weekend is real money. Either bound each session from
inside the instance:

```bash
sudo shutdown -h +240        # hard stop in 4 hours
```

or attach a CloudWatch alarm on `CPUUtilization < 5%` for 30 minutes with a **stop** action,
so an instance that finished its batch puts itself away.

## The stop/start cycle

```bash
aws ec2 stop-instances  --instance-ids i-xxxxxxxx
aws ec2 start-instances --instance-ids i-xxxxxxxx
aws ec2 wait instance-running --instance-ids i-xxxxxxxx
aws ssm start-session --target i-xxxxxxxx
```

Everything on the root volume comes back exactly as it was: the `bgperf/*` images, the venv,
`mrt/`, and your `results/` directory. Docker restarts on boot and re-reads the same image
store. There is nothing to rebuild.

If you are not using SSM, the public IP changes on every start. Fetch it rather than
remembering it:

```bash
aws ec2 describe-instances --instance-ids i-xxxxxxxx \
  --query 'Reservations[].Instances[].PublicIpAddress' --output text
```

An Elastic IP would pin it, at the cost of another $3.60/month and a resource you have to
remember to release.

## Resizing between benchmarks

This is the real payoff of keeping state on EBS. The instance type is an attribute of a
*stopped* instance, so you can move the same volume — same images, same venv, same MRT
files — onto whatever size the next benchmark needs:

```bash
aws ec2 stop-instances --instance-ids i-xxxxxxxx
aws ec2 wait instance-stopped --instance-ids i-xxxxxxxx
aws ec2 modify-instance-attribute --instance-id i-xxxxxxxx --instance-type r7i.12xlarge
aws ec2 start-instances --instance-ids i-xxxxxxxx
```

Run your neighbor sweeps, then resize back down to an `m7i.4xlarge` for everyday work.

One caveat if you care about comparability: **do not compare results across instance types.**
Different families, clock speeds, and memory bandwidths produce different absolute numbers.
Resize freely between *benchmarks*, but keep every run within a comparison set on the same
instance type — and record which type it was, because bgperf2 does not.

The volume can also grow without stopping anything, if 200 GB turns out to be tight:

```bash
aws ec2 modify-volume --volume-id vol-xxxxxxxx --size 400
# then, on the instance:
sudo growpart /dev/nvme0n1 1
sudo resize2fs /dev/nvme0n1p1
```

## What it costs while stopped

A stopped instance bills **nothing for compute**. You pay for:

* the EBS volume — gp3 is about $0.08/GB-month, so 200 GB idles at roughly **$16/month**
* any Elastic IP you allocated, about $3.60/month
* nothing else

That is the entire cost of keeping a fully-built bgperf2 environment on standby.

## Gotchas

**Root-owned files in `/tmp/bgperf2`.** The commercial NOS targets (cRPD, cEOS, SR Linux)
write files there as root that bgperf2 cannot clean up afterward. `/tmp` is on the root
volume, so these persist across stop/start and can make a later run fail confusingly. Clear
them with `sudo rm -rf /tmp/bgperf2`.

**The venv is tied to its interpreter.** `new_vm.sh` runs `apt upgrade`, and a distro Python
upgrade will orphan the venv. Symptoms are import errors on a setup that worked yesterday.
Rebuild it:

```bash
rm -rf venv && python3 -m venv venv && venv/bin/pip install -r pip-requirements.txt
```

**`build_bgperf.sh` is stale** — it invokes `bgperf.py`, which no longer exists. Use
`bgperf2.py`.

**Commercial NOS images are never built by `prepare`.** Download cRPD, cEOS, and SR Linux out
of band, copy them to the instance, and `docker load` them under the exact tags bgperf2 looks
up (`crpd:latest`, `ceos:latest`); anything else fails confusingly. Their licenses prohibit
publishing benchmark results.

**Results live in the repo directory,** so they persist with everything else — but they are
on a single EBS volume with no backup. If a set of runs matters, copy it off:

```bash
aws s3 sync results/ s3://your-bucket/bgperf2-results/
```

or take an EBS snapshot of the volume before you do anything risky.
