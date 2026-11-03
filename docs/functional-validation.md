# Run a small functional check promptly

For a newly prepared small correctness check, use the existing immediate recipe
CLI after authorization and prerequisite checks. Do not add hourly quiet-host
scheduling solely because the engine records elapsed time. A test of whether
100 correct routes arrive answers a functional question; its elapsed time does
not become a performance comparison.

This is a choice of execution protocol, not a new CLI flag or automatic runtime
authority. Existing frozen approvals, campaigns and queue jobs retain their own
admission rules. Never run alongside another BGP measurement or develop on an
active measurement host. Ordinary unrelated development activity may coexist
only under the selected functional protocol, with observations retained.

| Question | Preferred execution protocol |
| --- | --- |
| Does a small supported workload complete, deliver the expected count/set and clean up? | One immediate bounded functional attempt, retaining concurrent-activity observations. No CPU-idleness wait solely for timing quality. |
| Did latency, throughput, CPU or memory improve? | The separately approved comparison protocol, host qualification and configured quiet/contention requirements. Functional success does not qualify a performance difference. |
| Is reliable 10% slowdown detection established? | Deferred calibration campaign; no new authorization or policy activation follows from functional checks. |

## Freeze the question and retain the guards

Select an existing supported recipe, exact local role images and a clean engine
revision. For a 100-route smoke, declare at most one worker and a 120-second
worker budget, fresh work/results destinations, explicit memory/disk floors and
the storage decision. Missing images or dependencies cause refusal; prompt
execution is not permission to acquire substitutes. Source builds, repetitions,
larger workloads and extra probes require their own scope.

Keep the native measurement-lock/container guard, source/image identities,
destination and capacity checks, timeout/partial-result handling, owned cleanup
and package/assertion verification. The public prerequisite check reports
capacity, but it does not derive workload resource estimates or enforce an
operator's additional floors. Check the declared floors before executing.
Root-backed storage still requires the existing explicit exception where used.

Record the selected functional-only protocol with the attempt. Capture advisory
process/resource observations before execution, for example `ps -eo
pid,comm,pcpu,pmem`, `free -b`, and `df -B1` for the actual destinations. Process
CPU percentages are advisory historical averages, not an interval quiet-host
test. Do not expose private command arguments or infer exclusivity from one
snapshot. Preserve the existing runtime contention diagnostics and their missing
reasons. `raw-samples.csv` includes host idle/free-memory observations when
available; its metadata explains assurance-window slicing, so it is not a
complete continuous activity trace. Missing observations remain unknown.

## Use the existing public commands

Start with an approved recipe exported at the clean selected engine revision;
fixture image IDs must have been replaced with actual local identities. The
paths below are explicit placeholders, with new work/results destinations.
The commands are manual steps, not a script that grants execution authority.

```sh
venv/bin/python recipes.py check /absolute/artifacts/recipe.json \
  --workdir /absolute/disk/work/functional-001 \
  --results-dir /absolute/disk/results/functional-001
venv/bin/python recipes.py assertions-export /absolute/artifacts/recipe.json \
  --capability session_establishment --capability injection_completion \
  --capability observer_route_count --capability experiment_completion \
  --capability observed_role_health --capability observer_prefix_identity \
  --output /absolute/artifacts/assertions.json
# Explicitly authorized execution: one worker, immediately after prerequisites.
venv/bin/python recipes.py run /absolute/artifacts/recipe.json \
  --observer-prefixes --timeout 120 --diagnostics basic \
  --workdir /absolute/disk/work/functional-001 \
  --results-dir /absolute/disk/results/functional-001
venv/bin/python recipes.py result-verify \
  /absolute/disk/results/functional-001/result.json
venv/bin/python recipes.py assertions-check /absolute/artifacts/assertions.json \
  --result /absolute/disk/results/functional-001/result.json
```

`--observer-prefixes` requires a supporting sink image and the existing capture
limits. Omit that option/capability when identity is not selected; do not call a
count-only result identity validation. The [prefix contract](observer-prefixes.md)
defines the final-snapshot boundary. Explicit artifact-store/converter bindings,
when selected, must accompany all commands consistently; see
[artifact storage](artifact-storage.md). A copied reference tree without its
store is not complete evidence or an independent backup.

Accept only the declared functional evidence. A timeout or unavailable capture
is not a prefix mismatch, and competing activity is not an excuse to turn a
failure into a pass. Preserve partial packages, logs, observed load and cleanup
state. Do not automatically retry a consumed finite attempt. An uncertain
launch/cleanup requires reconciliation before another worker.

The [real-BIRD prefix validation](plans/observer-prefix-runtime-validation.md#successful-existing-image-worker--2026-11-03)
passed one 100-prefix worker in 12.088 seconds. Earlier attempts incurred hours
of admission waiting; the successful case05 waited about 28 minutes from
enrollment to dispatch at the next hourly check. Those waits were orchestration
costs of the selected lab policy, not requirements of this public CLI. That
historical run retains its original quiet-host policy.
Future small functional checks should select this immediate protocol explicitly.
Performance policy remains disabled and formal 10% calibration deferred.
