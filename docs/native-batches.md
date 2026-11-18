# One native batch, including interruption recovery

Use a single ordinary batch YAML containing the selected daemons, immutable
target/generator/observer images, workloads and repetitions. On an idle,
prepared host, start one controller:

```sh
venv/bin/python bgperf2.py -d /data/bgperf-work batch \
  -c comparison.yaml --results-dir /data/results/comparison-01 \
  --durable --calibrate --defer-graphs
```

Use the same start options with `--list-cells` to inspect the complete finite
plan, including calibration originals, without runtime probes or result creation.
This is structural planning, not runtime qualification.

Inspect or explicitly continue the same saved batch:

```sh
venv/bin/python bgperf2.py batch \
  --results-dir /data/results/comparison-01 --status
venv/bin/python bgperf2.py batch \
  -c comparison.yaml --results-dir /data/results/comparison-01 \
  --resume --defer-graphs
```

Resume recognizes durable state and its calibration policy; those two start
flags need not be repeated. The work/results volume, definitions and immutable
images must still be available. Keep the same graph mode and explicit shuffle
seed, if selected. First execution requires fresh results. A missing marker is
not permission to overwrite existing evidence.
Resume uses the saved work root; an explicit different nondefault work directory
is refused rather than relocating originals. Status needs only the results path.

The engine runs the whole selected matrix serially in one process. Calibrations
are separate originals, one for each configuration/workload. They run before the
test's measured passes. A failed calibration blocks only that configuration's
measured positions. Measured repetitions preserve the existing matrix/pass
order; calibration rows never enter measured CSVs or R3 summaries.

Every original retains its unique native receipt, artifacts and work directory.
Required regular output files and directory entries are flushed before its
terminal receipt attests durable storage. A durable batch refuses to adopt a
completion lacking that attestation.
`native-batch.json` records the plan, calibration dependencies, host/boot/source
facts, attempts and completed/failed/interrupted/blocked/unrun positions.
The exclusive `.native-batch.lock` is a held lease, not a stale-file test.
Status is read-only and starts no worker or Docker probe.

An ordinary native failure with verified cleanup is recorded as a failed row
with unavailable timing/resource fields, retains its original receipt, and
allows independent work to continue. Existing report summaries exclude failed
rows. Blocked positions remain unmeasured and are named in native batch status;
the older pass summary describes their absent observations as not run. Cleanup
or receipt uncertainty stops the controller and stays unresolved. Existing
`--stop-on-failure` may request an earlier stop.

On explicit resume, completed and ordinary failed positions are not rerun.
A completed receipt published just before the controller was killed can be
adopted without another measurement. For an interrupted position, the engine
records retained ownership snapshots/logs, stops and removes only its owned
containers/network, and starts a fresh original. A shared network or preservation
failure stops recovery before deletion. Previous attempts are never overwritten.
Container images, volumes, mounted work and unrelated containers are untouched.
Recovery retains inspect/log evidence; it does not claim a whole writable
container-filesystem archive or an independent backup.

Scope: native exact-input MRT or generated plain BIRD/sink IPv4 transit, with
the existing native restrictions and three immutable image IDs. External
`--control-dir` supervision and selected-cell `--cells` execution keep their
separate existing interface. This mode adds execution accounting, not measurement
instruments, probes, convergence changes or a weaker acceptance policy.
Host capacity/quiet-host/swap/resource policy and research comparison acceptance
remain the caller's responsibility. The engine records source and host epochs;
it does not infer that timings from different host sizes are comparable.

There is no daemon tuning, cloud watcher, instance launcher, automatic restart
or automatic retry of an ordinary failure. After host loss, restore the retained
volume with existing infrastructure tooling and invoke explicit resume. This
new mode does not adopt closed Lab campaign originals or reclassify historical
results. Local modeled checks qualify the state machine; a real interruption
validation is a separately selected future measurement.
