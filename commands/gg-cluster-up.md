---
description: Bring up a Greengage demo cluster, or attach to and verify an existing one
argument-hint: "[docker | local | attach]"
---

Get this session talking to a working Greengage cluster. Mode: $ARGUMENTS

Load the **greengage-cluster-ops** skill — it owns the mode gate and the provisioning
recipes. This command drives it; the skill has the commands and the failure modes.

## Decide the mode first

If the user did not say, work it out rather than guessing:

- **attach** — a cluster is already reachable. Signs: `PGPORT`/`PGHOST` are set,
  `pg_isready` succeeds, or a `gpdemo-env.sh` exists and its cluster is running.
  **This is the default whenever a live cluster is found.** Never create a second cluster
  on top of a running one.
- **local** — this is a Greengage source checkout with a build installed, and no cluster
  is running. Provision with the in-tree demo cluster.
- **docker** — no local build, or the user wants isolation. Provision from the images in
  `ci/`.

State which mode you chose and why before doing anything.

## Then

**attach:** source the right environment, confirm `SELECT version()`, and run the
health checks from `/gg-health`. Report the version line, the segment count, and any
segment that is down or failed over. Change nothing.

**local:** build if needed (**greengage-build**), then create the demo cluster and source
its generated environment file. Verify with `gpstate` and a `psql` round trip. The
skill has the exact commands, the required environment, and the tuning variables
(`PORT_BASE`, `NUM_PRIMARY_MIRROR_PAIRS`, `WITH_MIRRORS`, `DATADIRS`) — read it rather
than inventing flags.

**docker:** build the image from `ci/`, run the container with the semaphore
`--sysctl` setting the skill specifies (a cluster will not start without it), create the
cluster inside it, and verify the same way.

## Report

The mode, the connection parameters the user needs (`PGPORT`, data directory, container
name if any), the version, and the segment topology. If provisioning failed, give the
failing command and its output — do not summarise an error away.

Destroying or recreating an existing cluster is destructive. Ask first, every time.
