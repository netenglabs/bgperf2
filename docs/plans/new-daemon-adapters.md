# New daemon adapters for characterization

Selected 2026-11-07. Status: rustbgpd implementation in progress; other entrants
await their separate compatibility/integration checks.

## Purpose and ownership

Extend the engine's reusable adapter/build/recipe interfaces so newly selected
implementations can participate in ordinary IPv4 loading studies. Research
owns version selections, expected behavior, matrices and outcomes; lab owns
serial execution, admission, pressure guards and preservation. Public engine
use must not require private campaign files or a particular checkout layout.

The candidate set motivating this work is rustbgpd, Holo, zebra-rs, Bio-Routing
and Maghemite. An implementation's deployment compatibility and measured
correctness are separate from adding a registry entry. Do not turn unsupported
deployment or missing observations into a successful benchmark.

## First adapter: rustbgpd 0.81.0

This is distinct from osrg/RustyBGP. Upstream release source is
`eb1749d7018cd9691e4f4c9adef3b9adb830e9a8`. Repackage the official release
runtime image at immutable multi-platform digest
`ghcr.io/lance0/rustbgpd@sha256:f8a6d62ced049e415d702e31c43cbd6dac62fa9bcfdd0f410938f3c6cc418a64`.
It contains the production release-profile/jemalloc binaries and the `rbgp`
CLI. Record binary/image identities; a source label is not independent proof
of binary-to-source correspondence. Preserve upstream licenses and source ID.

The engine wrapper supplies root execution, iproute2 and its normal idle shell
for the existing container ABI, resets startup and disables inherited health
probes. It does not rebuild or replace upstream binaries. The adapter writes
ordinary eBGP IPv4 neighbors with explicit permit-all import/export policies
and uses the local operator Unix socket. No external API credentials or host
network service is needed. Forward daemon logs into the mounted work directory.

Upstream's JSON `prefixes_received` is backed by
`PeerSessionState.prefix_count`, documented as accepted prefixes and computed
from accepted-route accounting. Expose it only as accepted-prefix evidence.
Do not manufacture a pre-policy received count or a table/best-path witness.
Malformed, duplicate, stale or unavailable CLI observations must be explicit
read failures, never zeros or successful checkpoints.

## Acceptance

1. Register versioned preparation, verification, target dispatch and bounded
   supplied-image recipes; preserve old adapter behavior and identities.
2. Keep target diagnostics, process-contention accounting and counter semantics
   consistent with the new daemon and its CLI. Crash witnesses remain BIRD-only;
   local source builds/revision search remain BIRD/FRR-only.
3. Refuse unsupported filters, thread overrides and custom configuration/scenario
   paths before teardown at bench, scenario, config and batch entry points.
4. Test configuration, parsers, versions, recipe dispatch and early refusals
   without Docker. Run the required code review and quality gate before commit.
5. Build/verify the pinned release wrapper, record its provenance, then perform
   a bounded independent exact-prefix functional admission through the existing
   CLI. Retain failures and every original; no performance qualification follows.

Other candidates follow the same process after their interfaces are inspected.
New policy/attribute workloads and verdict semantics are separate changes.
