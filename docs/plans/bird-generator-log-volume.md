# Bound BIRD generator log volume

Selected by the operator on 2026-11-18. Logging changes are explicitly permitted
for fresh runs; closed measurements retain their source identities and logs.

The S5m local calibration wrote about 35 GB of generator logs. Most messages
are reflected-route `Invalid route` / `NEXT_HOP` remote messages that the health
scanner already excludes. Keep the selected log classes and BIRD's daemonized
startup, but stream through a per-peer FIFO and awk filter before disk. Retain
all other messages, flush each retained line, and unlink the FIFO after startup;
ordinary work preservation must not encounter special files. Existing images
already contain awk. Do not change daemon versions, workload generation,
offering counters, observer evidence, timing definitions or error acceptance.

Validation: exercise suppression and unchanged health counts with a large mixed
stream, execute generated startup with quoted paths, run the engine pure suite,
and verify real BIRD startup using the existing image. Review before commit.
Fresh comparisons must record the new engine identity; earlier timings are not
matched controls for a claim about the effect of logging.
