# Shared local artifact storage

The optional `bgperf2/artifact-store/v1` transport stores identical bulk files
once, compressed with Zstandard and addressed by the SHA-256 of their original
bytes. Recipe/result identities, experimental statuses and measurement clocks
are unchanged. Compression, verification and reclamation occur after the
backend returns, while the recipe host lock is still held.

## Enable for new attempts and reports

Select an absolute persistent store outside source checkouts and outside the
work/results trees. For example, use sibling `store/`, `attempts/` and `work/`
directories on a persistent data volume:

```sh
export BGPERF_ARTIFACT_STORE=/absolute/data/store
venv/bin/python recipes.py run recipe.json \
  --workdir /absolute/data/work/attempt-001 \
  --results-dir /absolute/data/attempts/attempt-001
```

Existing run prerequisites, clean source pins and runtime authorization still
apply. Setting the variable does not start an experiment. Without this explicit
binding, existing expanded-package behavior is unchanged.

New result collection writes `.log`, `.conf` and `.parquet` files of at least
1 MiB directly into the store. Small metadata, JSON, CSV and plots remain
expanded. Comparison and investigation packaging uses the same transport when
a destination store is explicitly configured. Without that binding, reports
materialize inputs without writing to the source store. Repeated checkpoints
register references rather than copying bulk artifacts. Different attempts
remain different observations even when some object bytes are identical.

After a result verifies and its metadata is synced, a recipe run reclaims only
the original bulk work files that match the stored checksums. This requires an
explicit empty `cleanup_errors` list from the backend and no artifact collection
failure. Failed and interrupted experiments retain their original statuses.
Unknown/failed cleanup retains work. Reclamation errors never rewrite an
experimental verdict; they are reported with the remaining work retained.

## On-disk contract

```text
store/
  objects/ab/<64-hex-raw-sha256>.zst
  roots/<registration-sha256>.json
  staging/.pending-<unique>
  index.sqlite
  reclamation-<timestamp>.jsonl
  gc-<timestamp>.json
attempt/
  result.json
  recipe.json
  .artifact-store.json
  work/<small retained metadata and plots>
```

`.artifact-store.json` contains exactly `schema`, `store` (an absolute local
binding), and `files` (logical relative path to object reference). A reference
contains exactly `sha256`, `size` (original bytes) and `codec: zstd`. Unknown
fields, unsafe paths and symlink components are refused. This catalog is
transport metadata; it does not add a scientific artifact or change the result
schema. Every logical file remains bound by the original result's checksum.
Report checksum manifests additionally cover their package catalogs.

Readers prefer a materialized physical file and otherwise resolve the nearest
catalog within the package. Every object read verifies decompressed size and
SHA-256, including when the consumer reads only a prefix. Verification rejects
unlisted catalog entries and absent or corrupt objects. A local reference
package depends on its bound store; copying its small directory alone is not
a backup or a portable return package.

Writers serialize publication and GC with a store lock. Objects and registration
records use exclusive atomic publication and directory/file fsync; existing
objects are verified before reuse. Registrations precede package catalogs.
Interrupted collection retains original work and may leave staging or orphan
objects. Referenced partial evidence remains pinned. Source files changing
during collection or reclamation are refused, rather than silently replaced.

## Verify, export and recover

```sh
venv/bin/python recipes.py result-verify /absolute/data/attempts/attempt-001/result.json
venv/bin/python artifact_store.py verify --package /absolute/data/attempts/attempt-001
venv/bin/python artifact_store.py export \
  --package /absolute/data/attempts/attempt-001 --output /absolute/return-package
```

Export materializes original logical paths into a new directory, removes the
local catalog binding and rebuilds comparison/investigation transport checksum
lists. Result files and their artifact checksums are preserved. Exports verify
without the original store and remain compatible with expanded-package readers.
Full directory bundles are produced on explicit export rather than for each
checkpoint. Export never overwrites an existing destination.

The generic `capture --source ABS --output NEW_ABS --store ABS` command supports
stopped lab work through the same public CLI. It records omitted runtime socket
paths and refuses symlinks and other nonregular artifacts. After stopping all
writers, `reclaim --source ABS --package ABS --writers-stopped` verifies the
catalog and metadata, journals every removal and reclaims only identical stored
files. It leaves small work files and all evidence references intact. This
explicit command is not an idle-host check: automated callers must hold their
measurement locks and establish that writers stopped.

Capture accepts one stopped work tree or one stored package. Compound report
trees containing nested catalogs must use `export`, or capture each constituent
package separately, so object registrations and transport checksum lists cannot
silently lose their bindings.

## Maintenance and retention

```sh
venv/bin/python artifact_store.py maintain --store /absolute/data/store
venv/bin/python artifact_store.py maintain --store /absolute/data/store --apply
```

The first command reports only. Apply verifies all registered objects,
rebuilds the SQLite search cache, and removes only abandoned staging and
unreferenced objects older than the grace period (24 hours by default; at least
one hour). A missing object, corrupt registration or checksum mismatch stops GC
before any removal. The SQLite database is rebuildable and never decides what
to retain. Removing it loses no evidence.

Registrations are permanent roots in this version. There is no age-based expiry,
automatic release of failed attempts, or deletion of referenced evidence.
Releasing retained observations requires a separately designed explicit policy.
Maintenance must run while measurement is idle. The lab provides a wrapper and
user timer that acquire both recipe and work-root measurement locks, inspect
local containers, and inherit those locks into maintenance. No scheduler is
installed or enabled by the engine. Deployment and independent backups remain
the consumer's responsibility.

## Optional Parquet sample tables

The worker already retains the graph series in `raw-samples.csv` with explicit
scope metadata. To add typed Parquet without modifying the locked measurement
environment, prepare a separate converter environment:

```sh
python3.14 -m venv /absolute/parquet-environment
/absolute/parquet-environment/bin/python -m pip install -r parquet-requirements.txt
export BGPERF_PARQUET_PYTHON=/absolute/parquet-environment/bin/python
```

With storage enabled, recipe finalization invokes the converter after backend
cleanup. It writes `raw-samples.parquet` with Zstandard compression, typed
columns, source checksum, row count and scope metadata. Null observations remain
null; counts are integers and percentages are floats. The bounded writer uses
65,536-row batches and exclusive publication. The source CSV remains unchanged
for compatibility; Parquet is explicitly derived rather than a second authority.
`parquet-export.json` records success or unavailability. Converter failure keeps
the source evidence and does not alter the experiment's observed status.
Integral decimal byte values emitted by the legacy engine, such as `512.0`, are
accepted without rounding. Converter staging stays in the configured store,
outside the captured work tree, under an inherited GC lease. It is removed on
timeout; abandoned converter directories are collectible after the grace
period. Failure to write the optional receipt is a
warning, so the completed attempt still proceeds to evidence collection.

Cross-attempt table compaction, chunk-level deduplication, remote object stores
and evidence expiry are not implemented. This version removes full-file copies
at the producers while preserving existing result and report semantics.

## Offline storage smoke

```sh
venv/bin/python scripts/artifact_storage_smoke.py --output /absolute/new/storage-smoke
```

This maintained example uses explicitly simulated backends and bypassed runtime
checks. It executes no benchmark, build or Docker operation. Two attempts and
three checkpoint transports share two bulk objects, verified work is reclaimed,
an independent export verifies, and maintenance rebuilds the index. The optional
Parquet binding is exercised when supplied. Its output supplies storage evidence
only, with no hardware or performance qualification.
