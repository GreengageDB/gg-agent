---
name: greengage-overview
description: Orient on a Greengage cluster or checkout and route to the right skill. Covers what MPP changes in PostgreSQL - distribution policy, Motion nodes, slices, GPORCA vs the Postgres planner, heap and append-optimized storage - plus 6.x/7.x version detection, coordinator/segment/mirror/standby anatomy and gp_segment_configuration. Use when a request says "Greengage", when you must tell 6.x from 7.x before typing a command, or on `connections to primary segments are not allowed` or `COORDINATOR_DATA_DIRECTORY not set!`.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "7.x (6.x deltas noted)"
---

# Greengage: orientation and routing

Read this first, act from a sibling skill second. Everything here is either a fact you
need before typing any command, or a pointer.

## Greengage is not a bigger PostgreSQL

Greengage is an open-source MPP analytical database continuing the Greenplum lineage on a
PostgreSQL base (7.x = PostgreSQL 12.22, 6.x = PostgreSQL 9.4.26). It is shared-nothing: a
**coordinator** holds only metadata, N **primary segments** hold all user data (usually
each with a **mirror**), and an optional **standby coordinator** shadows the coordinator.
Clients connect only to the coordinator, which splits each query into fragments and
dispatches them to the segments. The README says it in one sentence: *"All user data
resides in the segments, the coordinator contains only metadata. … Users always connect to
the coordinator server, which divides up the query into fragments that are executed in the
segments, and collects the results."*

Four PostgreSQL instincts break here. Everything else in this plugin is downstream of them.

| Instinct that breaks | What is actually true | Evidence |
|---|---|---|
| A table is just a table | Every table has a **distribution policy** — `DISTRIBUTED BY (cols)`, `DISTRIBUTED RANDOMLY`, or `DISTRIBUTED REPLICATED`. If you omit it, one is chosen for you. | `CREATE TABLE` synopsis: `[ DISTRIBUTED BY (column [opclass], [ ... ] ) \| DISTRIBUTED RANDOMLY \| DISTRIBUTED REPLICATED]`; catalog `gp_distribution_policy` (columns `localoid, policytype, numsegments, distkey, distclass`) |
| Cost is dominated by scans and joins | Cost is usually dominated by **Motion** nodes moving rows between segments. `explain.c` emits exactly five names: `Gather Motion`, `Explicit Gather Motion`, `Redistribute Motion`, `Broadcast Motion`, `Explicit Redistribute Motion`. Plans are cut into **slices** at Motions; each slice is run by a gang of segment processes. | `src/backend/commands/explain.c:1799-1813` |
| There is one planner | There are **two**: GPORCA (`optimizer=on`, the default when built with ORCA) and the PostgreSQL planner (`optimizer=off`). **Their costs are not comparable.** ORCA also falls back to the planner silently — read the footer to see which one ran, and `SET optimizer_trace_fallback=on` to have each fallback logged at INFO. | `guc_gp.c` `{"optimizer", …}` boot value `true` under `USE_ORCA`; `optimizer_trace_fallback` boot `false`, *"Print a message at INFO level, whenever GPORCA falls back"* (7.x `guc_gp.c:1840`, 6.x `:2134`); footer strings below |
| Storage is heap, full stop | Three storage types: heap, append-optimized row, append-optimized column. **Chosen at `CREATE TABLE` and not alterable** — changing it means creating a new table and copying. | Docs: *"Table storage and orientation can be declared only at creation."* |

The EXPLAIN footer that tells you which optimizer ran is **spelled differently on the two
lines** — grep for the wrong string and you will conclude the footer is missing:

| Line | Planner footer | ORCA footer |
|---|---|---|
| 7.x | `Optimizer: Postgres-based planner` | `Optimizer: GPORCA` |
| 6.x | `Optimizer: Postgres query optimizer` | `Optimizer: Pivotal Optimizer (GPORCA)` |

## Establish version and mode before typing a command

Half the wrong answers about Greengage come from running a 6.x command on 7.x. Two
questions, in this order.

### Which version

On a live cluster:

```sql
SELECT version();
-- PostgreSQL <base> (Greengage Database <ver> build <n>) on <host>, compiled by ...
```

The string is built by `configure.in` as
`"PostgreSQL $PG_VERSION (Greengage Database $GP_VERSION) on $host, …"`, and `$GP_VERSION`
comes from `./getversion` (`<git describe> build <BUILD_NUMBER|dev>`). Read the first
number: **`PostgreSQL 12` means Greengage 7; `PostgreSQL 9.4` means Greengage 6.** If the string says
`Greenplum Database`, you are not on Greengage — see
[migration from Greenplum](https://greengagedb.org/en/docs-gg/current/migrate_from_gp.html),
whose *Changes to server version string* section covers exactly this and warns that drivers
and monitoring that parse the string must be updated for the new product name.

In a source checkout, `VERSION` is git-ignored and only exists after `./configure` has run.
Read the source of truth instead:

```bash
git rev-parse --abbrev-ref HEAD                 # 7.x or 6.x are the two live branches
sed -n '23,24p' configure.in                    # AC_INIT + PG_PACKAGE_VERSION
# 7.x: AC_INIT([Greengage Database], [7.0.0-beta.0], …) / [PG_PACKAGE_VERSION=12.22]
# 6.x: AC_INIT([Greengage Database], [6.0.0-beta.1], …) / [PG_PACKAGE_VERSION=9.4.26]
./getversion                                    # "<git describe> build <BUILD_NUMBER|dev>"; works
                                                # in a fresh checkout — `configure` is committed
```

There is no `6X_STABLE`/`7X_STABLE`. Tags are plain SemVer with no `v` prefix (`7.4.1`,
`6.31.0`). **`main` is a stale mirror of 6.x** — the README line telling you to submit
features against `main` is inherited Greenplum text and is wrong here; see
[greengage-contribute](../greengage-contribute/SKILL.md).

### Which mode you are in, and where it routes

| Signal | You are in | Route to |
|---|---|---|
| `psql` connects; `SELECT count(*) FROM gp_segment_configuration` returns rows | a live cluster | [greengage-cluster-ops](../greengage-cluster-ops/SKILL.md) |
| `configure.in` + `gpMgmt/` + `src/backend/cdb/` present, no `greengage_path.sh` under `--prefix` | a source checkout, not yet built | [greengage-build](../greengage-build/SKILL.md) |
| `$prefix/greengage_path.sh` exists | an installed tree | source it, then see below |
| `gp*` utilities abort with `Environment Variable COORDINATOR_DATA_DIRECTORY not set!` (7.x, `gpMgmt/bin/gppylib/commands/gp.py:1230`; 6.x says `MASTER_DATA_DIRECTORY`, `gp.py:1207`) | installed but not fully sourced | also `source gpAux/gpdemo/gpdemo-env.sh` — `greengage_path.sh` alone is not enough |
| `/etc/os-release` inside a container built from `ci/Dockerfile*` | a CI/dev container | [greengage-ci](../greengage-ci/SKILL.md) |
| Nothing installed | starting from zero | [set up a demo cluster](https://greengagedb.org/en/docs-gg/current/set_up_demo_cluster.html), then [greengage-build](../greengage-build/SKILL.md) |

The environment script is **`greengage_path.sh`**, generated at install by
`gpMgmt/bin/generate-greengage-path.sh` into `$(prefix)/`. Never look for the Greenplum
name.

## The 6.x / 7.x deltas that change a command

Only rows that change something you would type. Full inventory in
[reference/version-deltas.md](reference/version-deltas.md).

| | 6.x | 7.x |
|---|---|---|
| PostgreSQL base | 9.4.26 | 12.22 |
| Terminology | master | **coordinator** |
| Data-dir env var | `MASTER_DATA_DIRECTORY` | `COORDINATOR_DATA_DIRECTORY` (gpdemo also exports the old name as an alias) |
| Utility-mode GUC | `gp_session_role` **and** `gp_role`, both default `dispatch`; only `gp_session_role` sets *both* (`cdbvars.c` `assign_gp_session_role`) | **`gp_role` only**, default `undefined`; there is no `gp_session_role` GUC — the name survives only as an obsolete alias remapped to `gp_role` (`guc.c:4761` `map_old_guc_names`) |
| Client utility mode | `PGOPTIONS='-c gp_session_role=utility' psql -p <segport> -d <db>` | `PGOPTIONS='-c gp_role=utility' psql -p <segport> -d <db>`. Because of the alias above, the **6.x spelling is the one that works on both lines**; the 7.x spelling does not — see the trap below. |
| `gp_toolkit` | plain SQL loaded by initdb (`src/backend/catalog/gp_toolkit.sql`, 45 views) | an **extension** (`gpcontrib/gp_toolkit`, `default_version = '1.9'`, 64 views installed; 58 `CREATE VIEW` in the base `--1.0.sql`, the rest from the upgrade scripts); `gpinitsystem` runs `CREATE EXTENSION gp_toolkit` in `template1` and `postgres` |
| Partitioning | Greenplum-style `PARTITION BY … SUBPARTITION TEMPLATE` only | that **plus** PostgreSQL declarative `PARTITION BY {RANGE\|LIST\|HASH}` |
| `default_table_access_method` | does not exist | exists (`guc.c:3792`) |
| `gp_resource_manager` default | `queue`; values `queue`, `group` | **`none`**; values `none`, `queue`, `group`, `group-v2` (`gpconfig:172`) |
| Copy files between hosts | `gpscp` | `gpsync` (rename) |
| Build | `make GPROOT=~/build PARALLEL_MAKE_OPTS=-j8 devel -C gpAux` | plain `./configure … && make -j8 && make -j8 install` |
| Rebalance utility | — | `ggrebalance` (Greengage-original). Not in `gpMgmt/bin/` at the `7.4.1` tag — it ships in 7.5.0+ and is documented only under [`/7/`](https://greengagedb.org/en/docs-gg/7/reference/utils/ggrebalance.html). Check `$GPHOME/bin/ggrebalance` exists before scripting it. |

## Route by intent

### Operating and querying a cluster

| If you are trying to … | Use |
|---|---|
| Start/stop, check health, recover or rebalance segments, add mirrors, expand, read `gpstate` | [greengage-cluster-ops](../greengage-cluster-ops/SKILL.md) |
| Pick a distribution key, choose heap vs AO row vs AO column, partition, fix skew, design DDL | [greengage-schema-design](../greengage-schema-design/SKILL.md) |
| Read an MPP `EXPLAIN`, kill a Broadcast Motion, choose an optimizer, fix spill files, run `ANALYZE` right | [greengage-query-performance](../greengage-query-performance/SKILL.md) |
| Bulk load — `gpfdist`, `gpload`, external tables, `COPY`, error tables | [greengage-data-loading](../greengage-data-loading/SKILL.md) |
| Resource queues vs resource groups, concurrency and memory limits, cgroup prerequisites | [greengage-workload-management](../greengage-workload-management/SKILL.md) |
| `gpbackup`/`gprestore`, incremental and partial backups, S3 plugin | [greengage-backup-restore](../greengage-backup-restore/SKILL.md) |

### Working on the source

| If you are trying to … | Use |
|---|---|
| `./configure`, build, install, prove the running binary is the one you built | [greengage-build](../greengage-build/SKILL.md) |
| Run `installcheck-good`, isolation2, behave; pick a schedule; create a demo cluster | [greengage-testing](../greengage-testing/SKILL.md) |
| Read or regenerate `.out` / `expected` files, `atmsort`, `gpdiff.pl` | [greengage-answer-files](../greengage-answer-files/SKILL.md) |
| Understand dispatch, gangs, interconnect, FTS, distributed snapshots, `src/backend/cdb/` | [greengage-internals](../greengage-internals/SKILL.md) |
| Attach gdb to a segment, read logs, use `gp_inject_fault`, diagnose a hang | [greengage-debug](../greengage-debug/SKILL.md) |
| Understand the GitHub Actions matrix, reproduce a CI failure in Docker | [greengage-ci](../greengage-ci/SKILL.md) |
| Open a PR: CLA, review rules, branch naming, where tests must go | [greengage-contribute](../greengage-contribute/SKILL.md) |

## Cluster anatomy: `gp_segment_configuration` is the topology table

Not `ps`, not the config files. One shared catalog describes the whole cluster on both
lines, with identical columns: `dbid, content, role, preferred_role, mode, status, port,
hostname, address, datadir`.

```sql
SELECT dbid, content, role, preferred_role, mode, status, port, hostname, datadir
FROM   gp_segment_configuration
ORDER  BY content, role;
```

| Field | Values | How to read it |
|---|---|---|
| `content` | `-1` = coordinator **and** standby coordinator; `0 .. N-1` = one segment pair each | Content is the *logical* slot. Two rows share a content: the primary and its mirror. |
| `dbid` | unique per database instance | The physical instance id, unique cluster-wide. 6.x hard-codes the coordinator as `MASTER_DBID 1`; do not assume a stable dbid for anything else. |
| `role` | `p` primary, `m` mirror | What this instance is doing **right now**. |
| `preferred_role` | `p` / `m` | What it is supposed to be doing. `role <> preferred_role` means a failover happened and the cluster is unbalanced but working. |
| `mode` | `s` in sync, `n` not in sync | Primary/mirror replication state. |
| `status` | `u` up, `d` down | Liveness as seen by the FTS. |

Symbolic values are defined in `src/include/catalog/gp_segment_configuration.h` (7.x) /
`src/include/catalog/gp_segment_config.h` (6.x), identical on both lines:
`GP_SEGMENT_CONFIGURATION_ROLE_PRIMARY 'p'`, `..._ROLE_MIRROR 'm'`, `..._STATUS_UP 'u'`,
`..._STATUS_DOWN 'd'`, `..._MODE_INSYNC 's'`, `..._MODE_NOTINSYNC 'n'`. Only the constant
for the coordinator content id was renamed: `COORDINATOR_CONTENT_ID (-1)` on 7.x,
`MASTER_CONTENT_ID (-1)` on 6.x.

**Trap: `mode = 'n'` on `content = -1` is normal, not a fault.** The coordinator row always
shows `n` and the standby row always shows `s`, and neither value describes coordinator
replication. The documentation states it outright: *"This column always shows `n` for the
master segment and `s` for the standby master segment, but these values do not describe the
synchronization state for the master segment."* `gpinitsystem` itself excludes the
coordinator when it waits for health — copy its predicate verbatim:

```sql
-- gpMgmt/bin/gpinitsystem, FORCE_FTS_PROBE: healthy cluster returns f
SELECT count(*) > 0 FROM gp_segment_configuration
WHERE (mode = 'n' OR status = 'd') AND content != -1;
```

Other anatomy facts worth having before you act:

- Segment count for sizing and skew maths:
  `SELECT count(*) FROM gp_segment_configuration WHERE content >= 0 AND role = 'p';`
- Every table exposes a hidden system column `gp_segment_id`
  (`GpSegmentIdAttributeNumber` in `src/include/access/sysattr.h` — attribute number **`-7`
  on 7.x but `-8` on 6.x**, because 6.x still carries `ObjectIdAttributeNumber`; never
  hard-code the number, use the name).
  `SELECT gp_segment_id, count(*) FROM t GROUP BY 1 ORDER BY 1;`
  is the fastest skew check; `gp_toolkit.gp_skew_coefficients` and
  `gp_toolkit.gp_skew_idle_fractions` are the maintained versions. On
  `DISTRIBUTED REPLICATED` tables the system columns are hidden outside utility mode
  (`src/backend/parser/parse_relation.c:730-740`, 6.x `:618-627`), so this query errors there.
- The interconnect between segments defaults to UDP (`gp_interconnect_type = udpifc`);
  `tcp` and `proxy` (needs `--enable-ic-proxy`) also exist.
- Fault detection is the FTS, a coordinator process polling segments (`src/backend/fts/`).

## What not to do

- **Never connect straight to a segment port to "check something".** You get
  `FATAL: connections to primary segments are not allowed`, detail *"This database instance
  is running as a primary segment in a Greengage cluster and does not permit direct
  connections."*, hint *"To force a connection anyway (dangerous!), use utility mode."*
  (`src/backend/utils/init/postinit.c:1278`, same text on 6.x at `:1200`). If you truly need
  it, use utility mode and change nothing.
- **Never assume `gp_role=utility` is the portable utility-mode spelling — it is not.** On
  6.x `assign_gp_role` (`src/backend/cdb/cdbvars.c:519`) sets `Gp_role` but leaves
  `Gp_session_role` at `dispatch`, so `postinit.c:1194` refuses the session with
  `FATAL: System was started in master-only utility mode - only utility mode connections
  are allowed` — a different error that looks nothing like the one you were working around.
  Only `gp_session_role=utility` sets both on 6.x, and 7.x remaps that name onto `gp_role`
  (`guc.c:4761`), so:
  ```bash
  PGOPTIONS='-c gp_session_role=utility' psql -p <segport> -d <db>   # works on 6.x and 7.x
  PGOPTIONS='-c gp_role=utility'         psql -p <segport> -d <db>   # 7.x only
  ```
  The management tools follow exactly this split: 6.x `gpcheckcat:3685` and
  `gppylib/db/dbconn.py:165` send `gp_session_role=utility`; 7.x `gpcheckcat:2640` and
  `dbconn.py:204` send `gp_role=utility`.
- **Never compare a GPORCA cost to a Postgres-planner cost.** Different cost models. Compare
  wall clock, or compare two plans from the same optimizer.
- **Never assume a PostgreSQL 13+ feature exists.** 7.x is PostgreSQL **12.22**; 6.x is
  9.4.26. Confirm in the tree before using anything newer.
- **Never trust a bare `origin/7.x` git ref in the greengage clone.** Local branches named
  literally `origin/7.x` and `origin/7.x_new` exist; git resolves the bare form to the wrong
  tree with only a warning. Always write `refs/remotes/origin/7.x`.
- **Ignore `concourse/` when asking "how is this tested".** It is legacy Greenplum CI. PRs
  run GitHub Actions (`.github/workflows/greengage-ci.yml`) delegating to pinned reusable
  workflows in `greengagedb/greengage-ci`.
- **Ignore `doc/` when looking for the user manual.** The tree's `doc/` holds only man-page
  reference sources; the manual is on greengagedb.org — map in
  [reference/docs-map.md](reference/docs-map.md).

See also: [greengage-cluster-ops](../greengage-cluster-ops/SKILL.md),
[greengage-schema-design](../greengage-schema-design/SKILL.md),
[greengage-query-performance](../greengage-query-performance/SKILL.md),
[greengage-build](../greengage-build/SKILL.md),
[greengage-internals](../greengage-internals/SKILL.md),
[greengage-contribute](../greengage-contribute/SKILL.md)
