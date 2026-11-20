# Fixed-input MRT performance with bench and batch

Use the normal performance CLI for routine full-table measurements. A native
cell uses the existing benchmark lifecycle directly; it does not export a
portable recipe, spawn a recipe worker or package/verify one portable result per
repetition. Recipes remain available for portable reproduction and investigation.

Implemented at `8b81540`, with exact full image-ID preflight in `0e7ea9d`. One
live fixed-input 24-peer batch qualified the interface and its fail-closed
lifecycle: serial admission/replay, exact-prefix capture, owned cleanup and
stop-on-failure after a failed final prefix identity. That does not qualify
every daemon/workload combination or a performance comparison. The run record
is in Git history at `docs/plans/native-mrt-performance.md`.

Select a source-only [MRT workload specification](mrt-recipes.md#input-bound-mrt-recipes)
before measurement. It binds the complete input's byte size/SHA-256, ordered
source peers and ASNs, offered counts, role ASNs and explicit expected prefix set.
The same schema and fixed-peer injector implementation serve both interfaces.

For one fresh cell:

```sh
venv/bin/python bgperf2.py -d /absolute/work bench \
  -t bird -g bgpdump2 -n 24 -p 1104164 --monitor sink \
  --image sha256:TARGET_ID \
  --generator-image sha256:GENERATOR_ID --observer-image sha256:OBSERVER_ID \
  --mrt-spec /absolute/workload.json --mrt-spec-sha256 WORKLOAD_SHA256 \
  --pin target=0-7,monitor=8-9,testers=10-15 \
  --results-dir /absolute/fresh-results
```

Replace each ID/hash with its full immutable digest. The topology peer count
must equal the workload length; `-p` is the largest declared source-entry count,
not the expected observer set size. Only fresh generated bgpdump2/sink transit
is supported with this opt-in: no `-r`, custom `-f` scenario, filters, receivers,
churn or policy reload. Existing commands without MRT binding retain their behavior.

Native batch target entries carry `mrt_spec`, `mrt_spec_sha256`, `image`,
`generator_image`, `observer_image`, `tester_type: bgpdump2`,
`mrt_injector: bgpdump2` and `mrt_file` (the bound input path), alongside the
usual target name/version/label/thread settings. Each test declares the usual
neighbor/prefix axes, monitor, placement and repetitions/order/seed. Workload
hashes and all image IDs are validated before the first worker; the target's
complete binding is part of the existing batch cell identity. For example:

```sh
venv/bin/python bgperf2.py -d /absolute/work batch \
  -c /absolute/performance.yaml --results-dir /absolute/fresh-results \
  --stop-on-failure
```

`--stop-on-failure` is opt-in for ordinary batches and stops after a failed row
has been recorded. Exact-input validation or lifecycle uncertainty raises before
a successor; it never creates a successful row. There is no automatic retry.
Do not reuse a results identity to replace evidence. Explicit ordinary batch
resume retains its existing cell/source compatibility requirements.

## Native evidence and measurement boundary

Every native MRT cell gets a new `bgperf_bench_<uuid>` identity, separate work
and artifact directories, and a compact `<attempt>.mrt.json` result receipt in
the batch results directory. It retains selected images, workload hash/path,
engine identity, the original stats row, whole-input verification before/after,
complete attempt-bound producer offering witnesses and exact final prefix-set
differences. The observer snapshot is retained in work. Owned containers and the
unique network are removed before the next cell; source work is retained.

The convergence rules, whole-second elapsed boundary and CPU/memory sampling
remain the existing lifecycle's. Input checks and final prefix capture are
outside its timed boundary. Observed ranges remain descriptive; final identity
and encode-side offering do not certify full attribute fidelity or wire drain.
Failure, cancellation, missing capture or cleanup uncertainty remains explicit;
interruption can lack an after-input check and never attests success.

## Optional operational supervisor

`--control-dir /absolute/existing/control` on native bench/batch offers an
external supervisor a bounded local handshake. It carries no lab policy.
Controlled MRT cells use the explicit bindings above. Bounded generated BIRD/sink
synthetic transit is also supported; see [native throughput controls](native-throughput.md).

The engine atomically writes `current.json` with the attempt identity and its
fresh child directory. It waits at most 1,800 seconds for
`admission-release.json` containing that exact attempt ID. Just before replay,
it writes the existing `pre-replay-ready.json` request and waits at most 125
seconds for an identical `pre-replay-release.json`. The normal measurement
lifecycle starts after release. Stop requests interrupt both waits. `done.json`
is written only after owned cleanup, with the terminal disposition.

A lab supervisor may apply its committed quiet-admission, memory/disk/CPU,
swap and campaign limits while one engine batch process runs. Keep analysis,
rendering, builds and tests off an active measurement host. Admission and the
finite run budget belong to that supervisor; they are not inferred from a
successful timing or a snapshot taken before measurement.
