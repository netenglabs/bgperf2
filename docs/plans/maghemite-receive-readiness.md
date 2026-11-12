# Maghemite receive/table-loading readiness contract

Prepared 2026-11-12 for the frozen Maghemite source
`277f4368d7b6e6c75bf339db132f8de1ac9b019a`. Image and workload selections
belong to the eventual explicit experiment, outside this portable design.
This is a proposed engine contract and readiness specification. No receive-side
worker or implementation is selected by this document. The existing transit
recipe, convergence tracker and its six assertions retain their meanings.

## Retained basis

The selected source's `bgp/src/session.rs:8406` adds received routes to the RIB
and disables redistribution; `bgp/src/router.rs:205` distributes originated
routes. The retained failed transit original established generator sessions and
completed injection but delivered zero of 200 expected prefixes to the observer.
That is incompatible with transit evaluation and remains failed evidence.

Native adapter configuration uses admin API version `13.0.0`, IPv4 NoFiltering,
first-AS enforcement and ordinary timers. The build retains its OpenAPI schema.
`mgd/src/rib_admin.rs:46` implements `/rib/status/imported` using `full_rib`,
while `:57` implements `/rib/status/selected` using `loc_rib`. Both optionally
filter address family and protocol. The schema represents a RIB as prefix keys
mapping to path sets. This supports a proposed post-loading identity receipt;
it does not establish a continuous receive counter or wire attribute oracle.
`prefixes_imported` and `prefixes_advertised` atomics are declared/read without
update sites in this revision; neither is admissible as a progress gauge.

The retained native API evidence covers router configuration and three Established
neighbours, including two generators with received UPDATE counters. Prefix
atomics still read zero. No imported/selected RIB response was captured: those
endpoints are source/schema supported, but their native identity, response size
and collection overhead remain unqualified. Existing diagnostics query a fixed
ASN 1000; the future receipt must bind the actual configured ASN and selected
peers, rather than silently reuse that default-ASN sample.

## Proposed explicit execution and receipts

A future separate receive-side selection must declare immutable target and
injector images, engine revision, source workload and exact offered prefix set
before launch, topology/peer identities, role pins, startup and whole-controller
deadlines, resource floors, pressure policy and a finite original budget.
Initially qualify a small synthetic case before selecting an MRT scale. Never
reinterpret a transit case or reuse its observer elapsed value as intake time.

Use the existing owned lifecycle, generator completion/health observations,
native quiet/pressure admission, cgroup samplers, source verification and bounded
cleanup. A distinct receive contract must refuse unsupported transit assertions
rather than mark them passed. It must preserve failed/interrupted packages and
explicit cleanup errors, verify package hashes and require all selected generator
sessions and complete offerings with zero reported errors/timeouts.

The receipt must retain API version, exact URI/query, request start/end monotonic
and wall timestamps, HTTP status, bounded raw response bytes, response SHA-256,
parser version and errors. Query only the owned target's loopback API. Retain
`/bgp/status/neighbors?asn=CONFIGURED_ASN` and imported/selected RIBs separately.
The reviewed schema names IPv4/BGP query values as
`?address_family=Ipv4&protocol=Bgp`; retain the exact request and validate its
versioned response rather than treating a declared query as proof of filtering. Parse canonical
IPv4 prefix keys with duplicate-key rejection and nonempty BGP path validation;
exclude static routes by validated protocol filtering or explicit path type.
Bind returned peer identities to selected injectors where available. Compare
unique imported and selected sets separately with source-derived expectations.
Exact union identity alone does not prove every peer's paths were retained.
An absent, truncated, oversized, malformed or unsupported snapshot is unmeasured,
never an empty set or success. Do not enlarge the current adapter's 8 MiB HTTP
bound silently: full-table API snapshots need explicit capacity qualification.
No snapshot may be streamed partially into a passing identity verdict.

After all generators report completion, take bounded sequential RIB snapshots
until a declared deadline, retaining every observation. An API snapshot exposes
one database read, not the precise arrival instant or atomicity across endpoints.
Without a documented cheap reliable gauge, frequent full-table polling can cost
substantial target CPU/memory and API serialization time. Qualify that overhead
before selecting a cadence. Two identical snapshots can establish observed
stability but cannot establish continuous identity between reads.

Record release-to-generator-completion and release-to-first-exact-snapshot
intervals with achieved polling/request resolution. Call the latter observed
API table readiness, with serialization and polling overhead; do not call it
transit convergence or compare it directly with observer delivery elapsed.
Keep first-prefix visibility unavailable unless a bounded native observation
actually captures it. Imported and selected snapshots may differ legitimately;
a future selection must state which is its primary oracle and why.

Retain sampled per-role cgroup CPU deltas and memory with exact sample intervals,
missing-member reasons and units. Distinguish target memory from host available
memory, API collection overhead and post-loading diagnostics. A failed or
unmeasured loading case has no successful loading-time statistic.

## Readiness disposition

Source/API review supports a concrete receive-side design. Implementation,
modeled refusal tests, required code review, small native qualification, API
size/atomicity/overhead assessment and a separately approved finite experiment
selection remain. This scheduled follow-up authorizes this preparation only;
no receive-side original is charged to or launched within the transit ceiling.

## Small post-worker qualification implementation

Explicit `recipes.py run --maghemite-receive` now selects a separate bounded
post-worker API qualification receipt for synthetic Maghemite cases with at most
two peers and sixteen prefixes. It requires basic diagnostics. Before replay,
the worker records the rendered source peer/prefix expectation. The parent
requires complete generator offerings and zero errors/timeouts, rechecks owned
immutable container identity before every query, and retains neighbour evidence
for the configured ASN plus two imported/selected snapshot pairs one second
apart. Requests share the existing twenty-second diagnostics budget and retain
at most 64 KiB including HTTP status framing; the HTTP client's 8 MiB safety
limit remains unchanged.

`work/maghemite-receive.json` contains the independent qualification status,
strict prefix/peer identity differences, timestamps, body hashes and bounded raw
response references. Whole-container cgroup CPU readings and current/peak memory
bracket each successful request; missing samples remain unavailable. They include
the HTTP client and daemon activity during those intervals, not isolated API
CPU overhead. The response pair is sequential, not an atomic cross-table read.

This flag changes no transit row or assertion. A failed transit result can carry
a passing API qualification receipt, and remains a failed transit result. The
receipt has no successful receive-loading or convergence timing. Small native
qualification, response size and observed collection cost must still be recorded
before any MRT receive-side selection. No general receive worker or scalable
polling implementation is claimed.
