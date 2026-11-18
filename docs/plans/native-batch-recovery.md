# Native batch recovery and calibration dependencies

Selected by the operator on 2026-11-17 after stopping the AWS comparison.
The objective is repository-owned execution and recovery, rather than an agent
reconstructing campaign state or assembling ad hoc commands. Development and
modeled qualification are local. No new measurement, daemon/image update,
infrastructure action, publication or migration of closed originals is selected.

## Ownership and user interface

The engine owns one serial native batch, durable attempts/results, explicit
resume, owned cleanup, calibration dependencies, independent failure handling,
and machine-readable progress. Lab owns installation, host preparation and
deployment through existing tooling. Research owns frozen comparisons,
acceptance and reports. An agent selects work and reviews results; it is not
part of the execution or recovery state machine.

Extend the existing `batch` CLI and cell identities. `--durable` selects the
new native execution contract; `--calibrate` adds one separate calibration per
configuration/workload before measured repetitions. `--resume` continues saved
state, and `--status` inspects it without starting work. A single YAML may cover
all selected daemons; fixed finite groups remain a research choice.

## Required behavior

- Keep completed, failed, interrupted, blocked and unrun distinct. A failed
  calibration blocks only its own measured positions. Continue independent
  configurations only after verified owned cleanup; cleanup uncertainty stops.
- Preserve every unique native attempt and original receipt. Manual resume
  skips successful and ordinary failed positions. It may create a fresh attempt
  for an interrupted position after safely recovering owned resources. No
  automatic process restart, cloud watcher, instance launch or retry loop.
- Adopt a completed native receipt after a crash between receipt publication
  and cell-result publication, avoiding remeasurement. Validate workload/cell,
  image, cleanup and result identities first.
- Hold an exclusive results lease. Refuse changed experiment definitions,
  unsafe paths or ambiguous receipts before running. Record host/boot and source
  facts per attempt; incidental hostname or MemTotal bytes do not gate generic
  execution. Research determines comparison cohorts from retained facts.
- Preserve current convergence clocks, samples, native input/offering/identity
  checks, immutable images and measurement rows. Calibrations remain separate
  from measured R3. Old CLI behavior and closed campaign originals remain intact.

## Delivery and validation

- [x] Implement native durable execution/status/resume and calibration gating.
- [x] Test success, independent failure, failed calibration, graceful stop,
      hard-loss recovery, completed-receipt adoption, changed inputs, cleanup
      rejection, exclusive locking and report separation using modeled runtimes.
- [x] Document one-batch operation and explicit resume; update the historical
      invariant placing all attempt accounting in external callers for this mode.
- [x] Complete local code review and required gates; commit the engine change.
- [x] Record Lab/Research handoff and retire the need for agent-directed recovery
      in future campaigns. Actual replacement of frozen campaigns and new native
      measurements remain separately selected for a later time.

Implementation is opt-in and extends the existing lifecycle, cell identities,
stats writer and reporting. The public [native batch guide](../native-batches.md)
owns the commands and recovery/status meanings. Modeled checks include a real
forked controller exiting without cleanup, followed by explicit recovery, plus
a public status command with no YAML and an invalid Docker endpoint. These are
software tests, not daemon, capacity or native interruption qualification.

The delivery commit is conditional on the repository's review and full Python
gate. The first review identified a CSV error-message escaping defect; the
fix uses the existing row formatter. Focused checks additionally cover unresolved
completion status, saved work-root recovery, retained recovery-history pointers,
and flushing native payloads before completion attestation. A stopped/incomplete
original never becomes an accepted timing through a report or resume operation.

## Selected local integration refinement, 2026-11-17

The operator selected completing the local Research/Lab integration after the
first engine delivery. Managed durable control now binds host-policy review
before checkpoint/next-cell admission, supports recovery without new work,
bounds fresh reservations per invocation and stores row column names. Existing
native clocks/images/guards and historical attempts are unchanged. Real daemon
or AWS execution remains stopped and separately selected. Focused recovery
checks include rejection, lost review, no-launch recovery and bounded resume.
