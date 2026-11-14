# Native throughput controls

`bench` and `batch` retain the existing lifecycle, CSV metrics, convergence,
assurance, image/version provenance, offering and exact-prefix checks. These
interfaces support finite external coordinators without depending on a lab.

```sh
venv/bin/python bgperf2.py batch -c matrix.yaml --list-cells
venv/bin/python bgperf2.py batch -c matrix.yaml --preflight --defer-graphs
venv/bin/python bgperf2.py batch -c matrix.yaml --defer-graphs
venv/bin/python bgperf2.py render-bench --input /absolute/results --results-dir /absolute/fresh-graphs
```

`--list-cells` is offline: Docker connection and NumPy/Matplotlib imports are
lazy. It does not create result identities or probe a socket. Existing defaults
retain their canonical cell keys and ordering. `--preflight` is separate runtime
validation for controlled native workloads: it validates every expanded cell,
full immutable target/generator/observer images and exact MRT inputs before any
worker. It creates no container, network or attempt. Host qualification, resource
policy and scientific eligibility remain the external caller's responsibility.
It does not acquire images or authorize execution.

`--defer-graphs` is opt-in on bench/batch. It suppresses periodic, final per-bench
and batch graph rendering while retaining CSVs, events, statistics and provenance.
It saves each bench's complete seven-column sampled graph data, units/schema and
content hash in `<prefix>.graph-data.json`. `render-bench` accepts a file or a
directory tree, preserves relative per-attempt directories and reconstructs the
six bench graphs through the existing graph function. Render into a fresh
output root on an idle host. A failure requires rerendering, never remeasurement.
Aggregate research figures can be generated independently from stored rows.

Deferred plotting changes prospective overhead, so batch identities include
`defer_graphs: true` and version manifests record it. Omitted/false uses legacy
identities. Do not combine these prospective groups with older plotted originals
without a separately justified compatibility decision. Source revisions and
originals are never rewritten by the option.

Native receipts bind an exclusive `phases.jsonl` operational journal to the
attempt, host, PID, sequence, UTC and monotonic origin. It records admission,
setup, pre-replay release, measurement completion, recording/rendering, exact
capture, input checks, owned cleanup and terminal status. Measurement completion
also records the existing start/stop wall timestamps after stopping the existing
clock. It does not redefine any CSV timing. Interrupted/missing phases remain
missing. Journal errors fail closed and cannot skip owned cleanup. Plain
uncontrolled legacy benches do not gain this journal automatically.

The [native MRT control handshake](native-mrt-performance.md) also supports
explicit controlled **generated BIRD/sink synthetic plain transit**, with three
immutable role image IDs. It uses the same lifecycle and validates exact disjoint
/32 expectations and complete attempt-bound per-generator offering witnesses.
It writes `bgperf2/native-result/v1` receipts; MRT retains its existing receipt
schema. `--control-dir` must exist and be absolute. Admission and replay releases
must match the attempt exactly; finite waits, cancellation and cleanup precede
terminal release. Unsupported generators, scenario files, repeats, filters,
receivers, churn, policy reload, path diversity and more than five million
synthetic prefixes refuse before a worker. Ordinary bench commands remain
compatible. Controlled synthetic support has modeled qualification only; select
a separate small live qualification before a large campaign.
