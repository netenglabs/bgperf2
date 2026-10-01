#!/usr/bin/env bash
#
# Run the sink's Go vet and tests, under the race detector, in the toolchain
# image the sink is built with.
#
# The image build already runs `go vet` and `go test` (sink.py), so an image
# cannot exist unless they passed. That build does not use `-race`, and it is
# slow to reach. This is the quick loop for editing `sink/`.
#
# The toolchain is read from `Sink.BUILD_VARS['go_image']`, the digest-pinned
# reference the recipe uses, and is never retyped here. A hand-typed
# `golang:1.25-bookworm` floats with every patch release, so a race run and the
# build could quietly use two different compilers.
#
# Usage: scripts/sink_go_test.sh [go test args...]   (default: ./...)
#   GOMODCACHE_DIR  host directory for the Go module cache, so repeated runs
#                   do not download gobgp again
#                   (default: /data/bgperf-work/gomod)
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python="${repo}/venv/bin/python"
[[ -x "${python}" ]] || python=python3

image="$(cd "${repo}" && "${python}" -c 'import sink; print(sink.Sink.BUILD_VARS["go_image"])')"
cache="${GOMODCACHE_DIR:-/data/bgperf-work/gomod}"
mkdir -p "${cache}"

if [[ $# -eq 0 ]]; then
    set -- ./...
fi

echo "toolchain: ${image}" >&2
# The source is mounted read-only: neither vet nor test has any reason to
# write to it, and a go.sum rewritten from inside a container would be an
# unreviewed change to what the recipe hash covers.
exec docker run --rm \
    -v "${repo}/sink:/src:ro" \
    -v "${cache}:/go/pkg/mod" \
    -w /src \
    "${image}" \
    sh -c 'go vet ./... && go test -race -count=1 "$@"' sh "$@"
