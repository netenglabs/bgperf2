# Follow-ups

Interim tracking. `bd` is present in this repo but its database was never
finished initializing (`issue_prefix` is missing from its config, so reads
return empty and writes fail) — once that's fixed, these belong in `bd`
instead and this file should empty out, not grow.

Both items below came out of the recipe-drift-detection work
(commit `9f2c9bf`, `docs/invariants/provenance-and-verify.md`'s "Recipe
drift" section). Neither is a live bug; both were deliberately left out of
that change as disproportionate scope.

## Stamp the real pre-sanitize version as its own build-time label

`checkable_versions()` (`bgperf2.py`) exists only because `built_versions()`
returns `sanitize_tag()`'d suffixes, which are lossy and not always
invertible back to the version `resolve_ref()`/`render_dockerfile()` need. A
tag built via `update <image> --version <ref>` outside the daemon's curated
`VERSIONS` list is therefore silently excluded from every `doctor`/`images`/
`prepare` drift check — not `ok`, `stale`, or `unknown`, just never asked
about.

This is the *safe* failure mode (say nothing rather than guess against a
possibly-wrong ref), not a wrong answer, so it's a completeness gap rather
than a bug. Storing the real version string as its own Docker image label
alongside `RECIPE_LABEL_KEY` at build time would let `recipe_status()` read
it back directly and remove the guessing-back logic entirely — but it needs
threading a new parameter through every daemon's `build_image()` override,
which is real surface area for a gap that only bites an ad hoc `--version`
build outside the curated list.

## Consolidate doctor()/images()/prepare()'s status-to-text formatting

`doctor()`, `images()`, and `prepare()` (`bgperf2.py`) each hand-roll their
own `try`/`except` around `recipe_status()` and their own mapping from
status (`ok`/`stale`/`unknown`) to printed text, across four near-identical
call sites. They already drifted once during review (`doctor`'s top-level
line paired `ok` with `unknown`, which `docs/invariants/provenance-and-verify.md`
says must never happen) and were fixed by hand at each site rather than in
one place.

A shared helper would remove the risk of that happening again, but the four
sites want meaningfully different verbosity (a full sentence with an
`update` command vs. a terse `(recipe stale)` table note), so this needs
design thought rather than a mechanical extraction — not a quick fix.
