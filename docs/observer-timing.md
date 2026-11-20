# Observer delivery timing supplement

`observer_timing.py` reads a **verified existing result package** offline. It
starts no worker or container. Its separate supplement leaves the legacy CSV,
engine convergence rules and portable comparison report unchanged. Existing
sink images already write the required monotonic count records; no instrument
rebuild, faster controller polling or change to the workload is implied.

```sh
venv/bin/python observer_timing.py \
  --result /absolute/results/attempt/result.json \
  --assertions /absolute/artifacts/assertions.json \
  --output /absolute/new/observer-window.json
venv/bin/python observer_timing.py \
  --result /absolute/results/attempt/result.json \
  --assertions /absolute/artifacts/assertions.json \
  --output /absolute/new/observer-window.json --verify
```

Select exactly the four worker-budget assertions in the
[comparison guide](comparisons.md). Package hashes, recipe binding, completed
status and all four assertions must pass before timing is inspected. There
must be exactly one packaged monitor `sink.log` and one sink event artifact.
The collected pre-cleanup instrument record must show one process, one
established session, the exact expected full count, and no lost sessions,
malformed records or kept/refused erroneous messages. Unsupported or ambiguous
evidence is refused with exit 2. This is deliberately a narrower input subset
than the runtime parser, including refusal of inverted timestamps and session
collisions. A refusal does not change the original experiment's status.

## Measurement definition

The metric is the **observer 10%-to-90% count-crossing window**, in seconds.
Its thresholds are `ceil(N/10)` and `ceil(9*N/10)`, where `N` is the recipe's
total prefix count. It measures the middle of this observer's receipt of the
table. Startup, the first 10%, the final 10%, assurance, configuration generation,
cleanup and packaging are outside this window. It is neither full convergence
latency nor a replacement for the legacy `elapsed (s)` column. It does not
establish which component limited delivery.

The sink's `C` record is stamped at the last UPDATE folded into its state.
Counts may be coalesced. A threshold crossing is bracketed by the timestamp
of the preceding count-bearing `C`/`H` record below the threshold and the first
such record at or above it. `H` must agree with the known count; `E` must agree
with the known count/UPDATE state. The parser accepts only the initial monotone
delivery through the first exact full count. A decrease/reset, restart,
malformed or incomplete record, session loss, erroneous message, missing full
count or absent crossing bracket in this prefix makes the metric unavailable.
Expected teardown resets after full delivery are outside the window; the
separate pre-cleanup instrument and assertion witnesses still qualify the
completed attempt. No claim is made that a checksum proves authentic execution
or that every omitted source log record can be detected.

Let the 10% crossing be in `[a0,a1]` and the 90% crossing in `[b0,b1]`.
The supplement retains both brackets and their observed counts, the recorded
endpoint difference `b1-a1`, and the conservative duration interval:

```text
lower = max(0, b0-a1)
upper = b1-a0
bracket width = upper-lower
```

Arithmetic uses integer nanoseconds before conversion to seconds. Both ends
use the same sink clock; subtracting them requires no host-clock alignment.
The nominal coalescing setting (currently 10 ms) is **not** a guaranteed error
bound: actual preceding count timestamps set the bounds. A late write, long
gap, coalesced burst or crossing first seen near startup cannot be repaired by
printing more decimal places. Both thresholds crossed in one record remain
unresolved. The supplement retains original artifact hashes, result/recipe and
assertion digests, engine identity and attempt ID. Verification reconstructs
the complete supplement from those original inputs and refuses edited prose
or observations. The supplement also records the analysis module's SHA-256;
use that same analysis revision to verify it. Source manifests are pinned and
checked again after inspection, and new output is written through a pinned
directory descriptor so a replaced parent symlink cannot redirect it into the
source package.

## Discovery screen

The fixed screen passes only when all three conditions hold:

- The duration's conservative lower bound is at least **one second**.
- The actual bracket width is at most **5% of that lower bound**.
- At least **ten increasing count records** lie strictly between the two
  thresholds.

These are proposed sampling adequacy requirements for the revised discovery
experiment. They are not a selected practical effect size, a statistical
power calculation or an accepted regression threshold. Unknown build and
instrumentation confounders remain. Performance is always `not_assessed` and
regression policy `disabled`.

Generation writes a new file and exits 0 for a passed screen or 5 for a blocked
screen. A blocked screen still retains its readable timing observations.
`--verify` never writes and exits 0 for an exactly reconstructed supplement,
even when the recorded screen is blocked. Verification is not gate acceptance.
Output must be outside the immutable source package; existing output files
are never overwritten. Keep supplements separate from original report bundles
and include them in the new analysis version's preservation inventory.

## Why the legacy clock is not enough

On the 200,000-prefix `comparison-pilot` cell every legacy monitor `elapsed (s)`
value was exactly 4 seconds. That value includes lifecycle time outside useful
delivery, so it cannot be scaled by a route-count ratio, and padding the run
does not improve its one-second resolution. The 10%-to-90% windows of those
packages were only about 0.11–0.15 seconds and all failed the screen above.
The 2,000,000-prefix [resolution pilot](../examples/recipes/comparison-resolution-pilot.yaml)
cell `e340b76986938b1c` passes: its windows had conservative lower bounds of
about 1.5–3.3 seconds, bracket widths of 0.7–1.7% of the lower bound and 65–232
interior records. The same workload on the repeatability recipe (cell
`8d043e8dc2f9f660`) behaves similarly.

## Comparing paired windows

Research analyses of repeated pairs use these definitions; the engine does not
compute them in reports. For a natural pair with windows `W_A` and `W_B` in
integer nanoseconds:

```text
d = log(W_B / W_A)
geometric change % = 100 * (exp(mean(d)) - 1)
crossing ratio bounds = [L_B / U_A, U_B / L_A]
```

`L` and `U` are each window's conservative lower and upper durations. The ratio
bounds describe timestamp resolution, not statistical confidence. For a local
same-image reference, the two-sided A/A envelope over that reference's pairs is
`E = max(1, upper_ratio_i, 1/lower_ratio_i)`; a candidate pair whose lower ratio
exceeds `E` shows observed sample separation only. Report every pair, keep
conditions, orders and chronological blocks separate, and do not pool cases,
fit order corrections, trim outliers or impute missing pairs. The sample SD of
`d` is a log-ratio dispersion, not a percentage coefficient of variation.

This tool authorizes no new measurement, scheduled launch, evidence transfer
or policy activation.
