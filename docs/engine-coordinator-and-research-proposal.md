# bgperf2 Engine Coordinator and Research Proposal

Date: 2026-10-08

Status: discussion proposal, saved at the operator's request. This records a
possible direction; it does not authorize implementation, migration, or
publication. Committing this proposal was authorized on 2026-10-10.

## The needs this addresses

bgperf2 now serves several purposes with different audiences and operating
requirements:

- Justin's own benchmark campaigns and comparison reports.
- Other users running a few tests or testing their own daemon.
- Storage of evidence and preparation of blog posts and papers.
- Unattended development of bgperf2.
- Unattended execution of experiments.
- Performance regression testing.

The current repository mixes the measurement tool with campaign definitions,
operating procedures, and publication material. Results need a durable home
outside the source checkout. Some future coordination software may be private
or proprietary, while the public tool should become easier to use.

## Proposed direction

Keep bgperf2 as a useful public measurement engine, build the coordination
system separately, and give research sources and evidence their own homes.
Preserve the measurement work already established in bgperf2. Rewriting the
engine would require reestablishing confidence in its measurements and edge
cases.

A simpler entry point can coexist with the existing capabilities. Users should
be able to run a small experiment without learning the campaign plans, Beads
setup, EC2 conventions, or unattended agent workflow.

This proposal concerns project boundaries and user experience. The existing
[architecture and benchmark roadmap](architecture-and-benchmark-roadmap.md)
discusses the engine's internal evolution; this proposal does not replace its
measurement work or the current operator contracts.

## Licensing finding

The discussion began with the assumption that bgperf2 was GPLv2. The inspected
checkout instead declares Apache 2.0 in [LICENSE](../LICENSE),
[bgperf2.py](../bgperf2.py), [base.py](../base.py), and several other original
modules. The report builder also carries an Apache 2.0 notice. Git history
records the license file as coming from the initial commit.

Apache 2.0 generally permits proprietary derivatives, subject to its license,
attribution, and modification notice requirements. The inspected evidence
therefore does not support needing a rewrite to make a coordinator proprietary.
See the [Apache license, sections 2 through 4](https://www.apache.org/licenses/LICENSE-2.0).

This finding is not a complete dependency or provenance audit. Third party
components and distributed daemon images have their own terms. Those should
be checked before commercial distribution. The proposed separation is useful
for maintainability and independent use regardless of the licensing outcome.

## Responsibilities and homes

| Part | Responsibilities | Proposed home |
| --- | --- | --- |
| bgperf2 | Daemon adapters, workloads, measurement, validation, local batches, basic summaries, beginner setup | Existing public repository |
| Lab coordinator | Campaign selection, provisioning, queues, retries, budgets, notifications, unattended agents, regression schedules | Separate private repository |
| Research and publications | Experiment definitions, analysis, claim documents, article and paper sources | Separate research repository, initially private |
| Evidence archive | Raw results, logs, manifests, input identities, derived datasets, published report versions | Durable object storage outside Git |

These boundaries do not require four services. The coordinator can initially
invoke a pinned bgperf2 version as a subprocess, pass an experiment
specification, and consume files. A network API is unnecessary for that first
step.

The public engine should remain independently useful. Its documented interface
should support ordinary users and the private coordinator equally. General
example workloads, measurement definitions, and correctness rules belong with
the engine. Justin's campaign choices and publication narratives belong with
the research.

## A portable result bundle

Formalize the result bundle as the first boundary. It should connect execution,
archiving, regression analysis, and publication without requiring access to the
original checkout or a particular `/data` directory.

Each bundle should identify:

- The experiment and execution attempt, including failed or interrupted attempts.
- The engine revision and daemon image identities.
- The host environment and input data identities.
- The experiment specification and rendered configurations.
- Measurements, logs, validity findings, and artifact checksums.

Existing manifests, event artifacts, and summaries provide much of this
foundation. The work is to make their contract portable and self describing.
Reanalysis should create a new analysis version that references the original
evidence. Corrections should preserve the original execution record.

## Evidence storage and publication

A practical initial choice is a private S3 bucket for evidence and a separate
Git repository for research sources, since execution already uses AWS.
Enable bucket versioning to help recover accidental overwrites and deletions;
it is disabled by default. See the
[S3 versioning documentation](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html).

The proposed storage rules are:

- Upload completed attempts between measurements, verify checksums, and mark
  the remote bundle complete only after verification.
- Keep raw evidence unchanged. Store revised analyses and reports as new versions.
- Maintain a small searchable catalog that can be rebuilt from bundle manifests.
- Publish selected evidence and report versions separately, with stable
  identifiers and explicit publication licenses.

The current `results/` directory is already gitignored. The missing pieces are
a durable archive and a way for reports to resolve their evidence. Another Git
repository for bulk results would address location without adequately
addressing their lifecycle.

The research repository should hold campaign YAML, analysis scripts or
notebooks, claim documents, and article sources. Reports should retain the
existing discipline of tracing numerical claims to evidence and using shared
measurement definitions. Moving publication material should preserve those
checks.

## Unattended development and experiments

The development workflow proposes code changes and runs checks. The experiment
workflow executes an approved specification against a pinned engine revision.
A new development commit should become an explicit candidate for validation
before later campaign runs adopt it.

Code work and reporting should run away from an actively measuring host. The
existing host isolation rules still apply; extracting a coordinator must not
introduce competing work during measurements.

Performance regression testing becomes a coordinator workflow: select a
baseline and candidate, run comparable repeated experiments, evaluate a
declared policy, and retain the evidence. Its outcomes must distinguish a
detected regression, an invalid measurement, and insufficient evidence. The
engine's provenance and withholding rules are useful foundations.

## A simpler public starting point

A local wizard should belong in the public project. A proposed
`bgperf2 quickstart` command could:

1. Ask whether the user wants a smoke test, a version comparison, or a custom
   daemon test.
2. Check prerequisites and prepare only the required images.
3. Suggest a small workload and explain what it measures.
4. Save an ordinary, editable experiment specification.
5. Run the experiment and show a short report with the evidence location.

This is a proposed command, not an existing interface. Saving the specification
lets users move from the wizard to repeatable CLI runs without starting over.
Custom daemon support also needs an adapter template and a validation command;
the wizard cannot remove that integration work by itself.

Documentation can improve before the extraction. For example, the inspected
README still says FRR is no longer compiled, while the current implementation
and agent documentation describe compiled FRR. The first experience should
match the current tool.

## Suggested sequence

The proposed sequence starts with the immediate storage need:

1. Establish the archive and bundle format. Copy and verify existing evidence
   before changing its current locations.
2. Create the research repository and move campaign and publication material
   with working evidence references.
3. Extract the coordinator incrementally, starting with the existing spot
   runner and queue.
4. Improve public onboarding, including the wizard and custom daemon path.
5. Add regression scheduling using the same engine and evidence contract.

The first useful milestone is an existing report rebuilt in a fresh checkout
using evidence fetched from the archive. That would deliver the storage
separation needed now and exercise the boundary the coordinator would later
depend on.

The storage provider, repository names, proprietary scope, publication licenses,
and detailed bundle schema remain choices to settle before implementation.
