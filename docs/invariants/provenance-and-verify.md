# Provenance and `verify`

Recording which build produced a result, and the one check the Docker-free test suite cannot make.

**Read this before editing:** `base.py` (`Container.version_string()`, `collect_provenance()`),
`bgperf2.py` (`verify`), and every module carrying a version command: `bird.py`, `gobgp.py`,
`rustybgp.py`, `openbgp.py`, `frr.py`, `frr_compiled.py`, `bgpdump2.py`, `exabgp.py`, `junos.py`,
`eos.py`, `srlinux.py`, `flock.py`, `monitor.py`, `tester.py`, `mrt_tester.py`

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
