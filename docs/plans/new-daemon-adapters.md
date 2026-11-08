# New daemon adapters for characterization

Selected 2026-11-07. Status: rustbgpd implemented at `0041e27`, with the native
ownership fix at `40a312e`; selected small live admission passed. Holo at
`9159d81`/`4c6487c` also passed its first small native admission. zebra-rs is
next; Bio-Routing and Maghemite await separate integration checks.

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
probes. It does not rebuild or replace upstream binaries.
The wrapper must also transfer `/var/lib/rustbgpd` from the release's UID 999
to the effective root UID and retain mode 0755: native startup rejects a control
socket parent owned by a different UID. The first bounded admission exposed
this packaging mismatch and timed out with verified cleanup; it is not a route
correctness or performance outcome. Preserve that original and use a fresh
attempt after the reviewed wrapper fix.

The adapter writes ordinary eBGP IPv4 neighbors with explicit permit-all import/export policies
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

## Next adapter: Holo 0.9.0

Source selection is `947daeb2811b0cb90f457458f35c3b1a3c989b6b`. Its release
has no binary assets and upstream container CI publishes moving latest tags.
Build the selected source with its tracked Cargo.lock, `--locked --release`,
and exact builder/runtime/client image digests. Preserve lock, proto, license
and observed source ID in the runtime image. Do not substitute upstream HEAD.
Retain compiler, resolved dependency tree and builder package inventory too.
Debian package repositories remain mutable; recorded package versions and
frozen binaries do not establish a bit-identical source rebuild.
The first native build exposed missing Protobuf well-known include files under
the minimal package installation. Install `libprotobuf-dev` explicitly alongside
`protobuf-compiler`; do not depend on recommended packages being installed.
Retain that original build failure. No Holo route worker ran at this checkpoint.

Holo separates daemon bootstrap TOML from transactional YANG configuration.
Use its exact-source `holo.proto` and generic grpcurl 1.9.3, with native gRPC
bound to container loopback and gNMI disabled. Startup must wait boundedly for
capabilities and commit the explicit permit-all IPv4 configuration before the
ordinary observer/generator lifecycle proceeds. Retain bootstrap, request,
commit outcome and daemon logs. No host service or external credentials.
Refresh generated YANG after Docker attachment resolves the actual benchmark
interface, before daemon startup; the constructor's default eth0 is not a
network identity. Capabilities probes are bounded at one second, startup Commit
at ten seconds and operational Get at five seconds. Native calibration still
must assess API sampling cost under load; those bounds do not qualify timing.

The native neighbor state provides `prefixes.received` from Adj-RIB-In
pre-policy and `prefixes.installed` from Adj-RIB-In post-policy. The latter is
accepted paths, not selected best paths. Read both for established IPv4
neighbors through one bounded Get request; malformed/unavailable counts refuse,
and no independent table/best-path witness is inferred. Preserve normal
interface/next-hop resolution behavior; do not invent a synthetic next-hop
bypass to make an admission pass.

Reuse the rustbgpd acceptance checks above: public build/verify/dispatch and
bounded recipes, early unsupported-control refusals, explicit diagnostics and
process accounting, pure tests, required review and a fresh native exact-prefix
admission. This plan does not itself qualify the implementation or runtime.

Selected native validation completed on 2026-11-08: the exact-source optimized
image built after the explicit Protobuf-header fix, reported the selected full
commit and passed instrumentation verification. Its first bounded two-peer,
100-prefix-per-peer original passed all six existing assertions, including
the independent exact 200-prefix sink snapshot with no missing/unexpected
prefixes and verified cleanup. Native target checkpoints also exercised its
gRPC reader. This qualifies that small integration scope only; attribute/policy
controls, large-load sampling cost and performance remain unqualified.

## Next adapter: zebra-rs 26.11.1

Repackage the official resolute release archives in a digest-pinned Debian
runtime, verifying the published package SHA-256 before extraction. Preserve
the package's schema/assets, notices and original archive. No host installation,
service activation or recommended Cradle/eBPF data plane is needed for ordinary
BGP. The selected source tag resolves to
`f05909af203f7caa954e874babad7af1dcc6db2a`; package identity is verified, while
binary-to-source mapping remains a publisher claim.

Release archive hashes: amd64
`e829f2ebd6a4758d9c9f4560d8d5ecb0de811d8f13dd261c308e03096781b2ee`, arm64
`803a2e9442aa0a9ae13365b42d814e608b1a234733446651d043964309a54af4`.
Only catalogued, verified releases are selectable; do not guess hashes for
another version or silently install a moving latest package.

Write ordinary IPv4 neighbors and explicit permit-all inbound/outbound policy
in native startup YAML. Use the package's `zebra-rs` daemon and `vtyctl` with
an explicit container-local Unix endpoint. Retain the generated config/logs.
The native `show bgp summary` JSON has per-family `pfx_rcvd` snapshots of
pre-policy Adj-RIB-In (after protocol attribute checks). It does not attest
accepted or selected paths. Its established `state` field is the decimal count
string, not the word Established; require consistency with the numeric count.
Read only IPv4 Unicast, reject malformed/duplicate observations, and bound each
CLI request with a checked exit status. Native load still needs calibration.
Build-time version invocations check both packaged binaries can load in the
selected runtime; the public instrumentation/version verifier remains required.
Use a benchmark-specific alias for the deadline helper and account for that
process explicitly, without allowlisting unrelated timeout commands.

Apply the same public registration, capability/refusal, diagnostics, process
accounting, pure-test/review/build-verification and fresh exact-prefix native
admission gates above. No local source builder or BIRD-only witness is added.

Implemented at `e78e56c`. The first native original received both generator
checkpoints but exported zero of the expected 200 prefixes. Independent count
and identity assertions failed; the legacy completed stats row is insufficient
for admission. Cleanup and artifact verification succeeded. The retained logs
cannot establish path eligibility or next-hop state. Preserve that original;
do not bypass next-hop validation or claim an upstream cause without evidence.

The next diagnostic change extends the existing bounded collector with fixed,
read-only zebra-rs native snapshots, collected after all roles' baseline memory
and logs. Every exec repeats immutable ID/name/image/attempt ownership checks,
uses an in-container deadline, and shares the existing overall/output bounds.
Queries sample default synthetic addresses and do not dump the full RIB or
configuration. None changes assertion, convergence, memory or crash meanings.
Focused tests cover ownership drift, disabled/other adapters, baseline ordering,
partial output/failure, and shared deadline exhaustion. A fresh native diagnostic
original with the same image and exact-prefix oracle follows review and checks.

The fresh native diagnostic original exercised all six snapshots. The sample
path was selected, the native connected route and kernel lookup were valid,
and the summary held 200 prefixes in the observer's Adj-RIB-Out. The sink
received only End-of-RIB before the original ended. Upstream's `AdvInterval`
defaults eBGP to 30 seconds and buffers advertisements; the existing engine
no-progress deadline is 15 seconds. This supports a timer mismatch, not a
proven next-hop failure or wire export defect. Packaged version metadata reports
unknown source commit and dirty=true, so source correspondence remains limited.

The operator selected a documented one-second eBGP advertisement interval,
matching the existing FRR adapter, rather than a longer no-progress allowance.
Write native `router.bgp.timer.adv-interval.ebgp: 1` in generated YAML. Retain
the unchanged image and prefix oracle, preserve both failed originals, and use
a fresh original after review/checks. This is a benchmark setting, not a claim
about upstream default performance or a change to convergence guards.

The one-second setting landed at `fb9c969` after clean review and the full
3,311-test native gate (one optional skip). A fresh native original passed all
six assertions, including exactly 200 expected prefixes with zero missing or
unexpected, verified package integrity and empty cleanup. Both failed originals
remain preserved. This qualifies only small functional loading at that setting;
policy/attribute controls and timed/capacity qualification remain pending.

### Zero-observer convergence correction

The diagnostic originals additionally exposed a legacy convergence bug: a
completed target checkpoint advances stability while the observer is zero.
The ordinary gate can converge that zero series before the no-progress branch;
the latter also wrongly requires the stability count to remain zero. Independent
prefix assertions prevented admission. Correct this in a separate change:
require positive observer count for every convergence verdict and apply the
existing no-progress deadline regardless of target-driven zero-count stability.
No duration, prefix oracle, positive-route assurance or MRT regression rule
changes. Regression tests reproduce both the realistic target-only checkpoint
and contradictory observer-checkpoint input, plus later positive delivery.
Existing recorded MRT replay tests must remain passing. Retain original rows;
never rewrite historical failures as if the corrected engine produced them.

## Next adapter: Bio-Routing 0.1.10

Build source `f422dbad63bd7977e94a16aa0718fb9876df23ee` with a digest-pinned
Go 1.25.14 builder, the tracked go.mod/go.sum and `-mod=readonly`, optimized
ordinary Go build settings and CGO disabled. Retain source ID, module files,
license, compiler/module inventory and actual `go version -m` binary build
metadata. Use the same digest-pinned Debian runtime as other new adapters.
The service has no native version flag: explicitly retain UNKNOWN rather than
manufacture a requested version banner. Binary/source records remain required.

Write native YAML for ordinary IPv4 eBGP and explicit permit-all import/export
policy, using the configured local interface address rather than the router ID
when those differ. Retain upstream default logging and next-hop semantics.
Do not use the advertised ListSessions RPC: its implementation returns not
implemented. Read implemented loopback Prometheus metrics through a bounded
native HTTP client instead. Register a benchmark-specific client alias for
process accounting; do not allowlist generic curl or an interpreter.

At the selected source, `bio_bgp_route_received_count` is labelled a counter
but generated from the current Adj-RIB-In RouteCount before import validation.
Expose it only as received paths for established IPv4 peers in VRF `main`.
Accepted/rejected descriptors are not emitted; accepted and best-path witnesses
stay unavailable. Validate labels, duplicate/context conflicts and finite
nonnegative integral values; missing/stale/malformed observations are read
failures, never zero or successful checkpoints. HTTP reads need deadlines,
response bounds and checked command exit status.
The runtime is Debian 13 (trixie), verified natively from the selected digest.
Require curl >=8.4.0 at build time and retain its actual version: the
[curl manual](https://curl.se/docs/manpage.html#--max-filesize) documents that
older clients do not enforce the size bound on bodies without Content-Length.
Thus old or incompatible clients refuse preparation instead of weakening the
streaming bound. Bio-Routing peer endpoints use native local-address with CIDR
stripped; router IDs remain distinct. Existing rustbgpd/Holo/zebra-rs adapters'
peer/router-ID distinction needs a separate reviewed correction for overridden
monitor addresses; default-address native qualifications remain scoped as run.

Apply existing registration, early unsupported-control refusals, pure parser/
configuration/build/dispatch tests, required review/native checks, immutable
image recording and fresh independent exact-prefix admission. No upstream
semantic patch, arbitrary scenario/config passthrough or new source-range
builder is included. Large-load sampling cost and policy controls remain
unqualified until their separate planned checks.

Implementation additionally closes the shared permit-all refusal gap for all
new adapters: nonzero AS-path, prefix, community and extended-community filter
counts must refuse at bench/config/batch entry points before teardown, alongside
the existing policy/thread/custom-file refusals. Ignoring a requested filter
would silently change the declared workload.

Implemented at `e965216`, clean final review and 3,423 native tests (one optional
skip). The pinned image built successfully; binary instrumentation verification
passed with explicit unavailable daemon version. Actual retained Go metadata
reports selected commit, vcs.modified=false, Go 1.25.14 and CGO disabled; curl
8.14.1 meets the enforced streaming-bound requirement.

The first native original failed before generator injection: both BIRD peers
reported Required capability missing (NOTIFICATION 2/7), and bio-rd logged that
notification as an invalid subcode. The existing corrected engine reported
FAILED with zero observer delivery and verified owned cleanup. Upstream's
native `advertise_ipv4_multiprotocol` neighbor option defaults false; its peer
builder includes the IPv4 multiprotocol capability only when explicitly enabled.
Enable that option for every configured neighbor, preserving ordinary IPv4
loading, image, independent prefix oracle and all guards. Review and test this
configuration correction before a fresh original; retain the failed original.
Do not weaken the BIRD capability requirements or modify upstream wire behavior.
