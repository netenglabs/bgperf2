# Bounded local review and validation reuse

Selected 2026-11-01 after a commit/push expanded into repeated broad reviews and
full-suite runs. Status: implemented, reviewed, validated and published in
engine `6eb876d`, with the public source snapshot interface in `376ca38`.
This plan authorizes tooling changes, not benchmarks, deployment or publication.

Scope is one reusable local review runner and conservative success receipts in
existing quality gates. Cross-repository delivery and worktree preparation are
delivered in consumer lab `bf682b4`; legacy evidence migration remains separate.
The lab consumes the engine's standalone checker through an explicit binding,
without copying it. Neither the lab nor its deployment is required by the engine.

Decisions:

- Freeze the complete staged diff; reject unstaged and untracked source changes.
- One broad review per invocation, with a five-minute default process-group
  deadline, retained prompt/diff/stdout/stderr and strict JSON findings.
- A fix uses focused verification of previous blocker IDs. Omitting a blocker
  cannot resolve it. Unrelated file scope or baseline changes require a new review.
- API failure text, malformed responses, timeouts and source mutation never
  produce ready reviews. Followups remain visible without blocking readiness.
- Cache only successful checks for at most 24 hours. Hash actual source bytes,
  file modes, untracked source, index, HEAD, Git configuration, complete command
  environment (hash only), interpreter/package inventory and runner source.
  Bound repositories and explicit optional Python environments participate.
  Normalize shell bookkeeping and verified default index paths. Git temporary
  commit indexes and unsupported source shapes run uncached instead of refusing
  an otherwise valid check. Directory symlink referents participate recursively.
- Keep HEAD/index/status in matching: provenance and source-preflight checks
  observe Git metadata. A commit can therefore require one new full run;
  repeated hook attempts at the same state reuse it. No claim of reuse across
  commit boundaries is made.
- Check source/environment again after validation. A failed/mutating run keeps
  logs but never publishes a successful receipt. Receipts are local operator
  records, not authenticated attestations or substitutes for hosted CI.
- Host guards, bootstrap verification, whitespace checks, clean push state and
  outgoing-tip selection remain fresh. Sink Go and lab integration have separate
  profiles; a Python success cannot cover either.

Acceptance:

- [x] Regression tests cover cache reuse, invalidation, hidden index edits,
  failures, mutation, timeout/API errors, malformed findings and focused reviews.
- [x] Existing engine and lab gate tests pass with normal check selection.
- [x] Full engine and lab suites pass; exact-state receipts record final runs.
- [x] CLI smoke verifies actual receipt reuse and stale review refusal.
- [x] Usage, limitations and next work documented.

Initial targeted validation: 48 engine tests and 12 lab gate tests passed.
The real bounded engine review returned one blocker concerning temporary Git
commit indexes; regression coverage now includes a real `git commit -a` with
a scratch hook, and that check runs uncached. Followups about shell environment
normalization and quoted API error text were also addressed in the same files.
The first lab CLI smoke found tracked directory skill symlinks, now supported
with content fingerprinting. Focused real reviews resolved both repositories'
blockers. The lab uses its verified local interpreter to launch the shared
standard-library checker, so pure lab checks need no engine virtualenv.

The first full runs passed 2,775 engine tests and 817 lab tests (three optional
lab integrations skipped). A later focused-response parser fix accepts resolved
followups alongside blockers, while still refusing omitted blockers. Targeted
coverage passed 49 engine tests and 13 lab gate tests. The live CLI smoke proved
reuse across separate tool invocations after excluding only the tool-call ID
from environment matching. Per-state final run logs/receipts live in ignored
`.dev-checks/`; writing validation history into tracked source changes its own
fingerprint, so receipts are the authority for the precise final checked state.

Remaining nonblocking limits: Git injects PATH/editor variables into hooks, so a
manual validation may miss even before HEAD changes; identical hook retries can
reuse their own receipt. The check deadline is 20 minutes, and arbitrary source
aliases can be unreadable. No claim of universal cache hits or external system
fingerprinting is made. Consumer delivery and worktree setup were completed in
the separately selected lab follow-on; their implementation stays with the lab.

No real model/network request is required to validate the runner protocol.
Maintained fake backends exercise the contract deterministically. An actual
provider review still needs its normal authentication and approved network
access; the runner never retries or changes permissions itself.
