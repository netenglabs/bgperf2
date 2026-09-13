# Provenance and `verify`

Recording which build produced a result, and the one check the Docker-free test suite cannot make.

**Read this before editing:** `base.py` (`Container.version_string()`, `collect_provenance()`,
`RECIPE_LABEL_KEY`, `recipe_hash()`, `img_recipe_label()`, `Container.current_recipe_hash()`,
`Container.override_buildargs()`, `Container.recipe_status()`), `bgperf2.py` (`verify`, `doctor`,
`images`, `prepare`, `checkable_versions()`), and every module carrying a version command: `bird.py`,
`gobgp.py`, `rustybgp.py`, `openbgp.py`, `frr.py`, `frr_compiled.py`, `bgpdump2.py`, `exabgp.py`,
`junos.py`, `eos.py`, `srlinux.py`, `flock.py`, `monitor.py`, `tester.py`, `mrt_tester.py`

These are invariants, not background: every rule here was written because the obvious alternative was tried and published a wrong number quietly. `CLAUDE.md` carries the one-line index; this file carries the argument.

---

## Recording versions — provenance

A result nobody can trace back to a build is not reproducible, so every run records the version
**and** image of all three roles, not just the target: the testers generate the load and the monitor
is the instrument the timings are read from.

- `Container.version_string()` is the only thing that should ever be called for this. It returns
  what the daemon reported, or a string starting `UNKNOWN` explaining why not — it never guesses.
  Commas are rewritten to `;` because rows are `','.join()`ed with no quoting.
- Each daemon's `get_version_cmd`/`exec_version_cmd` belong on the **daemon base class**
  (`BIRD`, `GoBGP`, `RustyBGP`), not the `*Target` subclass. `Monitor(GoBGP)` and
  `BIRDTester(Tester, BIRD)` inherit from the base, so a version command defined on the target was
  invisible to them and asking raised `NotImplementedError`. That is why only targets used to be
  recorded.
- Parse defensively. These parsers used to take a fixed word (`ret.split(' ')[2]`), which on an
  error message produced a plausible-looking value — `benchmarks/baseline/baseline-benchmark.csv`
  has two rows whose BIRD version is the word `exec`. Match the expected banner and raise
  `VersionUnavailable` otherwise.
- `collect_provenance()` asks one tester per distinct image and records a count, so a 100-peer run
  does not exec into 100 containers.
- Output goes two places: three columns appended to the **end** of the stats row (`target image`,
  `tester version`, `monitor version`) and a full `<prefix>.versions.json` manifest beside the
  graphs. Appending at the end is required — `create_batch_graphs()` indexes the row positionally.

Caveat worth knowing: a git ref pins source, not dependencies. RustyBGP gitignores its `Cargo.lock`,
so its builds resolve dependencies fresh and old refs rot — `340f521` (the 2024-12 commit the 2025
baseline benched) no longer compiles on any toolchain, which is why it is not offered as a version.

## verify — the check the test suite cannot do

`./bgperf2.py verify` starts a throwaway container per built image and asks the daemon about
itself. It exists because the unit tests deliberately cannot touch Docker, so nothing else covers
the seam where a parser meets a real container — and that is exactly where the bugs have been.
Both of these pass every unit test and are caught by `verify` in about a second per image:

- rustybgp read its version with **GoBGP's** parser (`RustyBGPTarget`'s MRO is
  `RustyBGP → GoBGPTarget → GoBGP`), recording `UNKNOWN` on every run.
- openbgpd looked for `bgpctl` under `/usr/local/sbin`, which does not exist in the image.

It also checks the daemon binary for gcov instrumentation, the defect that made every FRR result
incomparable for years. Notes for anyone extending it:

- Probe through the classes that really run the image — `TARGET_CLASSES` **and** `TESTER_CLASSES`,
  never the daemon base class. The rustybgp bug was invisible when the base was asked directly,
  because GoBGP is not in that MRO. `TESTER_CLASSES` exists for this: `bench` builds
  `ExaBGPTester(Tester, ExaBGP)`, not `ExaBGP`, and bird/gobgp run as both roles with different MROs.
- The throwaway container is created with `entrypoint=[]`. `command` is *appended* to an
  `ENTRYPOINT`, not run instead of it, so `bgperf/bgpdump2` and `bgperf/exabgp_mrtparse`
  (`ENTRYPOINT ["/bin/bash"]`) would run `bash sleep 600`, exit 126, and every later `exec` would
  fail with "not running" — while `dckr.start()` still returned success.
- The tag-vs-reported-version check runs only when the label could plausibly appear in a banner
  (`expect_version_in_banner`). `resolve_ref()` passes unrecognized values through as raw refs, so
  `update gobgp --version master` is supported and reports `3.38.0` — demanding the word "master"
  would fail a good image. Matching is anchored on a numeric boundary, because a bare substring
  makes `3.1` match `3.13`.
- An explicitly requested version that is missing, or a run that checked nothing at all, exits
  non-zero. A green result over zero checks is the one outcome a caller must not be able to trust.
- `VERSION_NEEDS_DAEMON` (FRR) means the version command talks to a running daemon over a socket,
  so a bare container cannot answer it — it is reported as unprobeable, not as broken.
- A daemon with no version command at all is a declared gap, not a failure; failing on it would
  make `verify` permanently red and therefore worthless.
- The gcov pattern is `GCOV_PATTERN`, and `.gcda` only counts where a **non-letter** follows.
  A bare `\.gcda` matches Go's `runtime.gcdata` and flags every gobgp image. Both halves were
  validated against a purpose-built instrumented/clean pair — a detector that never fires is worse
  than none.
- `verify` creates containers, so it is not in the permission allowlist alongside the read-only
  subcommands.

## Recipe drift — `RECIPE_LABEL_KEY`

`build_dockerfile()`/`prepare` skip a tag that already exists, so a recipe changed after that point
-- a new apt package, a fixed `ENTRYPOINT`, a `resolve_ref()` mapping a version onto a different
checkout -- is invisible until someone remembers to force a rebuild. That has happened three times
over (FRR's `--enable-gcov`, exabgp/bgpdump2's base image and `autoreconf`) and each was closed with
a hand-written, date-stamped CLAUDE.md paragraph naming what predates what.
`img_recipe_label()`/`recipe_status()` replace the next occurrence of that with something checkable.

- **The hash covers `render_dockerfile()`'s text plus the buildargs it would actually be built
  with**, stored as a Docker image label rather than a `LABEL` line inside the Dockerfile, which
  would need to hash itself. An override Dockerfile is the same file for every version routed
  through it -- only `BGPERF_REF`/`BGPERF_VERSION` vary it, as buildargs, not text -- so the text
  alone would be blind to a `resolve_ref()` change for such a version. `Container.override_buildargs()`
  is the one place that pair is built, called by both `build_version()` (which builds it) and
  `current_recipe_hash()` (which has to fingerprint the identical shape), so the two cannot drift
  apart the way a hand-reconstructed copy in each would. `recipe_hash()` folds text and buildargs
  together through `json.dumps([text, buildargs])`, not a bare concatenation, which a sufficiently
  contrived Dockerfile could otherwise split two different ways to the same string.
  `build_dockerfile()` hashes *before* splicing in the operator's `http_proxy`/`https_proxy`, or a
  machine's proxy settings would manufacture staleness that has nothing to do with the recipe.
- **It is not a substitute for `PULL_BASE`.** OpenBGPD's `FROM openbgpd/openbgpd:latest` is the same
  text before and after upstream republishes new content under that tag, so this hash cannot see the
  exact drift CLAUDE.md's OpenBGPD section is about -- it answers "has the recipe bgperf2 owns moved
  on", not "does a moving upstream tag still point at what it did." `pulls_base()` is the existing,
  separate answer to that one.
- **Only checked against a trustworthy version string.** `built_versions()` returns sanitized tags,
  and `sanitize_tag()` is lossy (`'stable/10.1'` and a literal `'stable_10.1'` sanitize to the same
  string), so a built tag with no matching entry in `cls.VERSIONS` has no way back to the ref it was
  actually built from. `doctor`/`images` skip the check for such a tag rather than render against a
  guessed ref and report a real, unchanged build as `stale`.
- **`unknown` and `stale` are different claims and must not collapse.** `unknown` is every image
  built before this label existed -- there is nothing to compare, the same shape as bgpdump2's
  "commit unknown" for a pruned clone -- and `stale` is a real mismatch. Reading `unknown` as `ok`
  calls an unverifiable image current; reading it as `stale` sends an operator to rebuild images
  that are probably fine.
- **Nothing rebuilds automatically, but skipping is not silent any more.** `prepare`'s "skip an
  existing tag" behaviour is unchanged -- an unattended rebuild triggered by an unrelated recipe edit
  is its own hazard, and the campaign skills already treat `prepare` as fast and idempotent -- but
  `prepare` is the command an operator actually runs day to day, and `doctor`/`images` are a separate
  step easy to forget. A tag it is about to skip is checked the same way and named if `stale`, so the
  trap CLAUDE.md records three times over now surfaces at the point it actually bites rather than
  only in a report nobody asked for. `v` on this path is always trustworthy (`None`, an explicit
  `--versions` entry, or a raw `cls.VERSIONS` member), so it needs none of `checkable_versions()`'s
  guessing-back through a sanitized tag.
- Verified against a real build (`bgperf/openbgp:9.2`, forced): the label round-trips through
  `docker build`'s `labels=` argument and `dckr.images()`'s own `Labels` field with no extra
  `inspect` call, and editing the recipe without rebuilding flips `recipe_status()` from `ok` to
  `stale` while an untouched sibling tag stays `unknown`.
- **`labels=` is withheld below Docker API 1.23** (~Engine 1.11): docker-py raises `InvalidVersion`
  for it otherwise, on every build, and doctor()'s own minimum-supported-version check still accepts
  Docker as old as 1.9.0. The gate reads `dckr.api_version` -- already resolved once at client
  construction, so this costs no extra round trip -- via `docker.utils.version_gte()`, the same
  function docker-py's own `build()` uses internally to decide the identical question, rather than a
  version threshold invented here. A build on such a daemon still succeeds; it just cannot carry the
  label, the same `unknown` shape as an image built before this feature existed.
- **The printed remedy is `update`, never `prepare -f` on the same invocation.** `prepare()`'s
  `wanted` list always prepends the unversioned tag regardless of `--versions`, so following that
  remedy force-rebuilds the daemon's default tag -- and, without `--versions`, its entire `VERSIONS`
  list -- even when exactly one specific version was ever flagged stale. `update <name>` (bare, for
  the unversioned tag) and `update <name> --versions <v>` each touch only the tag named, which is
  what `doctor`, `images`, and `prepare`'s own skip warning all recommend now. `prepare`'s "everything
  requested is already built" line is withheld whenever it already printed a more specific remedy, so
  the generic `-f` hint cannot read as reassurance undercutting the warning one line above it.
