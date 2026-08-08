# Per-version Dockerfiles

Old releases do not always build with the current recipe. Most of the time the
difference is small — a different base distro, one extra package, a configure
flag — and belongs in `VERSION_BUILD_VARS` in the daemon's module:

```python
class FRRoutingCompiled(Container):
    VERSION_BUILD_VARS = (
        ('8.', {'ubuntu_version': '20.04', 'extra_setup': 'apt-get install -y libyang-dev'}),
    )
```

When a version needs a genuinely different Dockerfile, put one here instead:

    dockerfiles/<image-name>/<version>.dockerfile

`<image-name>` is the name used on the command line (`frr_c`, `bird`, `gobgp`,
…). The longest matching version prefix wins, so `10.1.1` looks for
`10.1.1.dockerfile`, then `10.1.dockerfile`, then `10.dockerfile` — one file can
cover a whole release series.

The file is used verbatim, not templated. Two build args are passed in; declare
the ones you use after `FROM`:

    ARG BGPERF_REF        # the git ref for this version, e.g. stable/10.1
    ARG BGPERF_VERSION    # the version as typed, e.g. 10.1

A Dockerfile here only applies to builds that name a version. The unversioned
`:latest` image always comes from the daemon module's inline recipe.

The image must end up with the same layout the daemon's target class expects
(binary paths, config directories, log locations) — bgperf2 execs into it and
parses its CLI output, so a differently-organized image will start but fail to
report neighbor state.
