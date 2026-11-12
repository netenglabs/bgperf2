# Explicit bounded zero-route startup allowance

Implemented at `f6cf925` on 2026-11-12. The public bounded recipe `run` operation
accepts `--zero-route-startup-seconds` as an integer from 15 through 120, with
the ordinary 15-second default. The lab or another caller must select a larger
allowance explicitly. No target-specific default or new convergence oracle is
introduced. See [recipe contracts](../recipes.md).

The selection crosses CLI/controller/worker boundaries, is retained in packaged
`work/diagnostic-options.json` when nondefault, and reaches the existing tracker
as a scoped argument. The existing observation/replay boundary, positive-delivery
requirement, checkpoints, regression/stability rules, exact-prefix assertions,
generator health and whole-controller deadline retain their meanings. A quiet
gate precedes that clock. Ordinary bench and existing recipe callers retain 15 s.

Focused tests cover invalid types and bounds, zero delivery through the selected
allowance followed by failure, and late positive delivery followed by ordinary
convergence. Recipe tests refuse invalid values before creating destinations.
The staged local code review completed without findings; both full native gates
passed 3,665 tests, with one optional skip. The unavailable standard review
backend was retained as not_ready, followed by an available read-only backend;
its failure was not treated as approval. Deployment-specific source selections,
measurement outcomes and evidence preservation belong to their consuming project.

This implementation is complete. A larger bound, a new timing policy or a
receive-only measurement contract requires its own explicit design/selection.
