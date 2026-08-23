# rustbgpd target

[rustbgpd](https://github.com/lance0/rustbgpd) is an API-first BGP daemon
written in Rust. The image compiles the daemon (`rustbgpd`) and its CLI
(`rbgp`) from a git tag.

```bash
./bgperf2.py update rustbgpd                       # build the pinned release
./bgperf2.py update rustbgpd --version 0.64.0      # any other release
./bgperf2.py bench -t rustbgpd -n 10 -p 1000
```

## Versions

Releases are tagged `v<version>`, so `--version 0.66.0` builds `v0.66.0`.
Anything that is not a release number passes through as a raw git ref, so
`--version main` or a commit sha also work.

Unlike the other compiled targets, the unversioned image is pinned to a release
rather than tracking a branch: rustbgpd tags a release roughly weekly, so two
`bgperf/rustbgpd:latest` images built a week apart would not be comparable and
nothing in the results would say why. `./bgperf2.py images` prints the ref the
default tag resolves to. Use `update rustbgpd --checkout <ref>` to point the
unversioned tag somewhere else.

The builder is pinned to the toolchain the workspace declares as its minimum
(`rust-version` in `Cargo.toml`), and `cargo build --locked` uses the committed
`Cargo.lock`, so a tag resolves the dependency graph it was tested against.
When a newer release raises the minimum, `base_image` in `rustbgpd.py` has to
move with it.

## Neighbor state

The daemon serves gRPC on an owner-only unix socket at
`/var/lib/rustbgpd/grpc.sock`, and the target reads `rbgp --json neighbor`
through it. Since rustbgpd v0.63.0 a local operator is authorized implicitly on
that socket, so the generated config carries no gRPC security block. (Older
configurations used `[security.grpc] enforcement = "legacy"`; that setting was
removed in the same release and a config carrying it is rejected at startup.)

## Policy is not supported

The target writes plain `[[neighbors]]` blocks and generates no policy, so
`--filter_test`, the `--*-list-num` policy options, and per-neighbor filter
assignments have nothing to translate into. Rather than run unfiltered and file
the result under a filter label, the target raises before any container starts.

## Event history

rustbgpd's durable event-history outbox shipped default-on in v0.31.0 and became
opt-in (`enabled = false`) in v0.32.0. The target builds any ref, so a
v0.31.0-or-earlier build would run with event history on and a later one with it
off; the outbox moves both memory use and convergence, so those rows would not
be comparable. Setting `RUSTBGPD_EVENT_HISTORY_OFF` to any non-empty value
writes `[event_history] enabled = false` into the generated config, normalizing
event-history state across the whole version range the target can build.
