---
name: greengage-backup-restore
description: Back up and restore Greengage, choosing the right tool. Covers gpbackup/gprestore (shipped outside the greengage repo), --timestamp identifiers, incremental backups, --leaf-partition-data, S3 storage plugins, pg_dump/pg_dumpall coordinator funnel, --gp-syntax, WAL archiving's %c escape, gp_create_restore_point PITR, and pre-restore checks. Use when planning or verifying a backup, restoring into another cluster, or on `Greengage expansion currently in process`, `--target-gp-dbid is required`, or `not in QD mode`.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "7.x (6.x deltas noted)"
---

# Backup and restore

## `gpbackup` is not in this repository — stop grepping for it

`git grep -il gpbackup` against `refs/remotes/origin/7.x` and `refs/remotes/origin/6.x` of
`GreengageDB/greengage` returns five files on 7.x (seven on 6.x), and every hit is a
*comment* about the `backups/` directory — `src/backend/replication/basebackup.c:213`,
`src/bin/pg_rewind/filemap.c:95`, `src/test/regress/README:39`. Nothing named `gpbackup`
exists under `gpMgmt/bin/`, which ships the `gp*` cluster utilities plus `analyzedb` and
`minirepro` — no backup tool at all.

**`gpbackup`, `gprestore` and `gpbackup_helper` are a separate Go product**, versioned
independently of the server: source `https://github.com/GreengageDB/gpbackup` (default
branch `master`), plugin `https://github.com/GreengageDB/gpbackup-s3-plugin`, docs
`https://greengagedb.org/en/docs-backup/current/` — a **different doc tree** from
`docs-gg`, so a `docs-gg` search for `gpbackup_syntax` finds nothing.

Concluding "gpbackup does not exist in Greengage" from an empty source-tree grep is the
single most common wrong answer here. It exists; it just ships elsewhere.

## Pick the tool from the failure you are insuring against

| Situation | Tool | Guarantee you get | Guarantee you do not get |
|---|---|---|---|
| Whole database, TB scale, must finish overnight | `gpbackup` / `gprestore` | Segments write their own data in parallel; no bulk data crosses the coordinator | Not a physical/block backup; restore replays DDL + `COPY` |
| One schema or a table list | `gpbackup --include-schema` / `--include-table` | Same parallelism, smaller set | Cannot mix `--include-schema` with `--include-table` |
| Only what changed since last night | `gpbackup --incremental` | Per-leaf-partition deltas | Useless without `--leaf-partition-data` on **every** backup in the set |
| Move a database to PostgreSQL, or to a different Greengage major version | `pg_dump` / `pg_restore` | Plain portable SQL, `--no-gp-syntax` strips MPP clauses | Everything serialises through the coordinator |
| Roles, tablespaces, resource queues/groups | `pg_dumpall --globals-only` (or `gpbackup` globals + `gprestore --with-globals`) | Cluster-global objects `pg_dump` never touches | `pg_dump` alone will restore into a cluster with no matching roles |
| Roll the whole cluster back to a point in time | WAL archiving + `gp_create_restore_point` + `pg_basebackup` | Cluster-consistent named restore point | No packaged utility drives it; you script it (see below) |
| A segment host died | `gprecoverseg`, not a backup | — | Mirrors are not backups |

## `gpbackup`: install it, then the commands that matter

Build from source on the coordinator host; the documented prerequisites are exactly two,
Go 1.20 or later and a defined `GOPATH`
([install](https://greengagedb.org/en/docs-backup/current/install.html)):

```sh
git clone https://github.com/GreengageDB/gpbackup.git
cd gpbackup
make depend
make build          # binaries into $GOPATH/bin (typically ~/go/bin)
make install        # gpbackup+gprestore into $GPHOME/bin, then reads
                    # gp_segment_configuration and gpsyncs gpbackup_helper out to
                    # every segment host — so it needs a running cluster
gpbackup --version

gpbackup --dbname marketplace                                   # full backup
gpbackup --dbname marketplace --include-schema sales            # one schema
gpbackup --dbname marketplace --leaf-partition-data             # incremental base
gpbackup --dbname marketplace --leaf-partition-data --incremental
gprestore --timestamp 20251006063113 --create-db
```

### The `--timestamp` is the whole identifier scheme

`gpbackup` prints one line you must keep — `[INFO]:-Backup Timestamp = 20251006063113`.
That `YYYYMMDDHHMMSS` string is the *only* handle on the backup. `gprestore --timestamp`
is the documented required argument and there is no "restore the latest" — omit it and you
get `Must provide --backup-dir if --timestamp is not provided` (`restore/validate.go`). A
malformed one is rejected by `gpbackup --from-timestamp`:
`Timestamp %s is invalid.  Timestamps must be in the format YYYYMMDDHHMMSS.`

Files land under `<datadir>/backups/<YYYYMMDD>/<YYYYMMDDHHMMSS>/` on every host
(`filepath/filepath.go`: `path.Join(baseDir, "backups", Timestamp[0:8], Timestamp, …)`), so
`ls $COORDINATOR_DATA_DIRECTORY/backups/20251006/` lists that day's timestamps (6.x:
`MASTER_DATA_DIRECTORY`). The coordinator holds the config, the DDL metadata, the
table-of-contents and the report; each segment holds its own compressed data files.

The searchable index is the history database on the coordinator:
`<coordinator datadir>/gpbackup_history.db` (SQLite; legacy `gpbackup_history.yaml`),
from `GetBackupHistoryDatabasePath()` in `filepath/filepath.go`. `--no-history` skips
writing it — and thereby breaks automatic base selection for the next `--incremental`.
Reports and logs: `gpbackup_<ts>_report`, `gprestore_<backup_ts>_<restore_ts>_report`,
`~/gpAdminLogs/gpbackup_YYYYMMDD.log`.

### Incremental backups: `--leaf-partition-data` is a prerequisite, not a tuning knob

The base full backup **and every incremental in the set** must carry
`--leaf-partition-data`. Without it there are no per-partition data files to diff against,
and `--incremental` is rejected. With no `--from-timestamp`, `gpbackup` reads the history
database to find the most recent backup whose options are compatible; pass
`--from-timestamp 20251017091457` to pin the base explicitly.

**Restoring a set and restoring one increment are different commands, and `--incremental`
is the one that does *less*.** For the whole set, name the newest timestamp and pass no
`--incremental`. `--incremental` restores only that one backup's data — "Other backups
from the same incremental backup set are ignored" — and is rejected without `--data-only`
(`Cannot use --incremental without --data-only`).

```sh
gprestore --timestamp 20250103091621                    # whole set, newest timestamp
gprestore --timestamp 20250103091621 --incremental --data-only   # one delta only
```

**Incremental sets do not survive a topology change.** The docs are blunt: "Incremental
backups can't be restored after changes in the cluster segment configuration, such as
cluster expansion." After `gpexpand` or `ggrebalance`, take a fresh full base.

### Flag combinations `gpbackup` rejects

Every row below is a `gplog.Fatal`, not a warning — the run stops.

| Combination | Why |
|---|---|
| `--jobs` with `--metadata-only` or `--single-data-file` | nothing to parallelise / one writer per segment |
| `--copy-queue-size` with `--jobs`, or **without** `--single-data-file` | `--copy-queue-size must be specified with --single-data-file` |
| `--plugin-config` with `--backup-dir` | the plugin owns the destination |
| `--incremental` with `--data-only` or `--metadata-only` | an incremental is defined by its data deltas |
| `--incremental` without `--leaf-partition-data` | `--leaf-partition-data must be specified with --incremental` |
| `--single-backup-dir` without `--backup-dir` | `--single-backup-dir must be specified with --backup-dir` |
| `--include-schema` with `--include-table` | only `--include-schema` + `--exclude-table` is allowed |
| `gprestore --jobs` on a `--single-data-file` backup | the single stream cannot be split |
| `gprestore --run-analyze` with `--with-stats` | two ways to populate the same statistics |

Full flag inventory and the remaining rejected combinations, both utilities:
[reference/gpbackup-flags.md](reference/gpbackup-flags.md).

### Storage plugins: the executable must exist on every host

`--plugin-config` points at a YAML file whose `executablepath` is resolved **on each
host**, not just the coordinator. The S3 plugin's own `make install` handles the binary —
it "copies `gpbackup_s3_plugin` to `$GPHOME/bin` on all cluster hosts". Anything else you
add, config file included, you push yourself:
`gpsync -f hostfile /home/gpadmin/s3-config.yaml =:/home/gpadmin/` — `gpsync`
(`gpMgmt/bin/gpsync`) is the 7.x rename of `gpscp`, an rsync-to-many-hosts wrapper; 6.x
still ships `gpMgmt/bin/gpscp`, and the only docs page is
[gpscp](https://greengagedb.org/en/docs-gg/current/reference/utils/gpscp.html) — there is
no `gpsync.html` in either tree.

```yaml
executablepath: $GPHOME/bin/gpbackup_s3_plugin      # full key list in the reference file
options:
  endpoint: http://10.92.40.164:3900
  bucket: test-backup-bucket
  folder: test/ggbackup
```

```sh
gpbackup  --dbname marketplace  --plugin-config /home/gpadmin/s3-config.yaml
gprestore --timestamp 20251021054129 --plugin-config /home/gpadmin/s3-config.yaml
```

A plugin is any executable implementing eleven commands — `setup_plugin_for_backup` through
`delete_backup`, and `--version` — invoked as `<plugin> <command> <config_path> [args…]`;
full contract in `plugins/README.md` in the gpbackup repo and in
[reference/gpbackup-flags.md](reference/gpbackup-flags.md).

### Restoring into a different cluster

```sh
gprestore --timestamp 20251006063113 --create-db          # target DB does not exist yet
gprestore --timestamp 20251006063113 --redirect-db staging
gprestore --timestamp 20251006063113 --resize-cluster     # different segment count
gprestore --timestamp 20251006063113 --with-globals       # roles, tablespaces, resqueues
```

- `--metadata-only` requires the objects **not** to exist on the target.
- `--data-only` requires them to **already** exist. `--truncate-table` needs `--data-only`
  plus a table filter.
- `--with-stats` only works if the backup was taken with `gpbackup --with-stats`;
  otherwise use `--run-analyze`, or run `analyzedb` afterwards.

### `gpbackup` refuses to run during a topology change

Two sensors in the gpbackup source (`utils/gpexpand_sensor.go`,
`utils/ggrebalance_sensor.go`) abort with these literal strings:

```
Greengage expansion currently in process, please re-run gpbackup when the expansion has completed
Greengage rebalance currently in process, please re-run gpbackup when the rebalance has completed
```

**`gprestore` aborts too**, it just phrases it differently ("…existing backup sets taken
with a different cluster configuration may no longer be compatible…"): both sensors route
through one `checkExtToolRunning`, which calls `gplog.Fatal`. Take a new full backup once
`gpexpand`/`ggrebalance` finishes. The rebalance sensor requires Greengage 7
(`GetMinGgdbVersion() == "7"`), the gpexpand one 6.

## `pg_dump` ships in the repo — and funnels the cluster through one node

`src/bin/pg_dump/` on both branches builds `pg_dump`, `pg_dumpall` and `pg_restore`, and
all three have Greengage-specific pages under
[reference/utils](https://greengagedb.org/en/docs-gg/current/reference/utils/pg_dump.html).
They work. They are also the wrong tool for a large warehouse, for one structural reason:

**Every row travels coordinator → client.** The docs say it plainly: "All data is streamed
through the coordinator instance and written to its file system or standard output" and
"the coordinator must have enough local disk space to store the full backup."
`pg_dump -j 8` opens nine connections (`njobs + 1`) and every one of them lands on the
coordinator: parallel dumps "are parallelized only on the query dispatcher (master) node,
not across the query executor (segment) nodes as is the case when you use `gpbackup`."

Disqualifying when the database exceeds coordinator-local disk, the window is shorter than
`total_bytes / coordinator_NIC_throughput`, or the coordinator also serves queries. Good for
DDL extraction (`-s`), small databases, and SQL a plain PostgreSQL server will accept.

```sh
pg_dump --gp-syntax marketplace > marketplace.sql   # keeps DISTRIBUTED BY / RANDOMLY
pg_dump --no-gp-syntax -s marketplace > schema.sql  # strips MPP clauses for PostgreSQL
pg_dump -Fc --dbname=marketplace > marketplace.dump
pg_restore -j 8 --dbname=restored_db marketplace.dump
pg_dumpall --globals-only > globals.sql             # roles + tablespaces
pg_dumpall --resource-queues --resource-groups > wlm.sql
```

Greengage-only behaviour you will not find in PostgreSQL docs (line numbers are 7.x):

| Fact | Evidence |
|---|---|
| `--gp-syntax` / `--no-gp-syntax` dump or strip the distribution clause; default follows the server type | `pg_dump.c:486`, `usage()` line "dump with Greengage Database syntax (default if gpdb)" |
| Using both: `options "--gp-syntax" and "--no-gp-syntax" cannot be used together` | `pg_dump.c:709` |
| Against PostgreSQL: `server is not a Greengage Database instance; --gp-syntax option ignored` | `pg_dump.c:904` |
| `pg_dumpall --gp-syntax` implies `--resource-queues` **and** `--resource-groups` | `pg_dumpall.c:370-371` |
| `pg_dumpall -r` is not a shorthand: `-r option is not supported. Did you mean --roles-only or --resource-queues?` | `pg_dumpall.c:286` (6.x `:274`) |
| `pg_dump` silently excludes the `gp_toolkit` schema on pre-7 servers | `pg_dump.c:952` |
| No user-defined triggers and no large objects, so `-S`, `--disable-triggers` and `--serializable-deferrable` do nothing | docs `reference/utils/pg_dump.html` |

More detail: [reference/pg-dump-deltas.md](reference/pg-dump-deltas.md).

## PITR: the only flow this tree actually supports

There is no `gppitr` utility. What exists is a **distributed restore point** plus ordinary
PostgreSQL WAL archiving, exercised end to end by `src/test/gpdb_pitr/test_gpdb_pitr.sh`
(driven by `make installcheck` in that directory). Read that script first. The two
functions:

| | 7.x | 6.x |
|---|---|---|
| `gp_create_restore_point(text)` | **built in** — `pg_proc.dat:11549`, C source `src/backend/access/transam/xlogfuncs_gp.c` | `CREATE EXTENSION gp_pitr;` — `gpcontrib/gp_pitr/gp_pitr--1.1.sql` |
| `gp_switch_wal()` | built in — `pg_proc.dat:11553` | same extension |
| `gp_stat_archiver` | built-in generated view (`src/backend/catalog/system_views_gp.in`) | created by the `gp_pitr` extension |

`gpcontrib/gp_pitr` **does not exist on 7.x** — the extension was folded into the backend,
so `CREATE EXTENSION gp_pitr` there fails and the functions are already present.

Why it is cluster-consistent, not just N independent points: `gp_create_restore_point`
takes `TwophaseCommitLock` in `LW_EXCLUSIVE` before dispatching
`pg_create_restore_point(name)` to every segment (`xlogfuncs_gp.c:91`), blocking
distributed commit-prepared broadcasts for the duration. Transactions that had already
written their distributed commit record get rebroadcast during recovery; those that had
not are gone. A per-segment `pg_create_restore_point()` gives you a torn cluster instead.

**Greengage extends `archive_command` and `restore_command` with `%c` — the segment
content ID.** This is the piece PostgreSQL habits miss: every segment on a host runs the
same `archive_command` string, so without `%c` they overwrite each other's WAL.

```
# postgresql.conf on the coordinator and every primary
wal_level = replica
archive_mode = on
archive_command = 'cp %p /backup/archive_seg%c/%f'
# on the recovery side
restore_command = 'cp /backup/archive_seg%c/%f %p'
recovery_target_name = 'nightly_2026_08_18'
recovery_target_action = 'promote'
```

**`wal_level = replica` is 7.x-only** — 6.x's `wal_level_options` are
`minimal | archive | hot_standby | logical` (`xlogdesc.c:30`), default `archive`, and
`replica` stops the instance from starting. 7.x keeps `archive` as a deprecated alias, so
`archive` is the value that works on both. The recovery settings move too: 6.x reads them
from `recovery.conf`, not `postgresql.conf`.

Both lines take `%p`, `%f`, `%%` and (in `restore_command`) `%r`, plus:

| Escape | 7.x | 6.x |
|---|---|---|
| `%c` segment content ID | yes (`pgarch.c:605`, `xlogarchive.c:193`) | yes (`pgarch.c:612`) |
| `%d` segment dbid | **no** — the `case 'd'` is gone | yes (`pgarch.c:613`, `xlogarchive.c:185`) |

Base backups are taken per segment with `pg_basebackup`, and Greengage adds a **required**
flag there too: `--target-gp-dbid`. Omit it and you get
`no target dbid specified, --target-gp-dbid is required` (`pg_basebackup.c:2539`).

`cannot use gp_create_restore_point() when not in QD mode` (`xlogfuncs_gp.c:79`) means the
call reached a segment — utility mode, `gp_dist_random()`, or a CTAS that pushed it down.
`EXECUTE` is revoked from `public` on both functions, so a non-superuser needs an explicit
grant. Step-by-step, with the segment-configuration rewrite the recovered cluster needs and
the full error table: [reference/pitr-flow.md](reference/pitr-flow.md).

## Standby and mirrors are not backups

A mirror is a byte-for-byte WAL replica of its primary; it replicates `DROP TABLE
customers` faithfully, in milliseconds, with no undo. The standby coordinator is the same
thing for content `-1`. Both protect against **hardware and process failure only**.

| Failure | Mirror / standby | Backup |
|---|---|---|
| Segment host dies | recovers it (`gprecoverseg`) | irrelevant |
| Coordinator dies | `gpactivatestandby` | irrelevant |
| `DELETE` without `WHERE` | replicated instantly | the only recovery |
| Bad deploy drops a schema | replicated instantly | the only recovery |
| Silent corruption from a bad upgrade | replicated instantly | the only recovery |

Second trap: `pg_basebackup` and `pg_rewind` **exclude the `backups` directory** from the
data directory (`basebackup.c:213` and `:249`, `filemap.c:95` and `:131` — comment: "GPDB:
Default gpbackup directory"). Default-located `gpbackup` output is therefore not carried
to a rebuilt mirror and not part of any base backup. Use `--backup-dir` on a filesystem
that is actually backed up, or a storage plugin. Cluster health and recovery themselves
live in [greengage-cluster-ops](../greengage-cluster-ops/SKILL.md).

## Verify the restore, or you have a hypothesis, not a backup

Restore into a scratch cluster or a redirected database and compare counts.

```sh
gprestore --timestamp 20251006063113 --redirect-db marketplace_verify --create-db
```

Generate one `count(*)` per non-leaf relation (leaf partitions are excluded via
`pg_inherits`, so a partitioned table is counted once through its root):

```sql
SELECT format('SELECT %L::text AS relation, count(*) AS rows FROM %I.%I;',
              n.nspname || '.' || c.relname, n.nspname, c.relname)
FROM   pg_class c
JOIN   pg_namespace n ON n.oid = c.relnamespace
WHERE  c.relkind IN ('r', 'p')
  AND  n.nspname NOT IN ('pg_catalog', 'information_schema', 'gp_toolkit', 'pg_toast')
  AND  NOT EXISTS (SELECT 1 FROM pg_inherits i WHERE i.inhrelid = c.oid)
ORDER  BY 1;
```

On **7.x** append `\gexec` in `psql` to run the generated statements immediately. On
**6.x** you cannot: `\gexec` does not exist in PostgreSQL 9.4 (`git grep '"gexec"'` on
`refs/remotes/origin/6.x` returns nothing) — write the output with `-At -o` and feed the
file back through `psql -f`. On 6.x also add `AND c.relstorage <> 'x'`, or the generated
statements `count(*)` external tables straight off gpfdist; 7.x needs no such clause,
because there external tables are foreign tables (`relkind = 'f'`) and `relstorage` is
gone. Check distribution survived too, not just totals:
`SELECT gp_segment_id, count(*) FROM sales.orders GROUP BY 1 ORDER BY 1;`

Then run `gpcheckcat` against the restored database — a restore replays DDL, so a catalog
problem present at backup time is reproduced faithfully:

```sh
gpcheckcat -O marketplace_verify        # online; -A for every database
gpcheckcat -g /tmp/repair marketplace_verify   # write repair SQL, do not auto-apply
```

Run `gpcheckcat` **before** the backup too: `gpbackup` reconstructs DDL from the catalog, so
a corrupt catalog produces a backup that restores into the same corruption.

## Check these five things before you restore

| Check | Query / command | Failure mode if you skip it |
|---|---|---|
| Segment count matches | `SELECT count(*) FROM gp_segment_configuration WHERE content >= 0 AND role = 'p';` | a different count needs `--resize-cluster`, and incremental sets cannot be resized at all |
| Cluster is healthy and unexpanded | `SELECT * FROM gp_segment_configuration WHERE status <> 'u' OR role <> preferred_role;` (`mode='n'` on content `-1` is normal) | `Greengage expansion currently in process…` |
| Server version | `SELECT version();` on source and target | 6.x is PostgreSQL 9.4.26, 7.x is 12.22 — a 6→7 move is a migration, not a restore |
| Roles exist on the target | `SELECT rolname FROM pg_roles;` | `pg_dump` never dumps roles; owners and GRANTs fail. Use `pg_dumpall --globals-only` or `gprestore --with-globals` |
| Tablespace paths exist on every host | `SELECT spcname, pg_tablespace_location(oid) FROM pg_tablespace;` | tablespace creation fails mid-restore |

Roles and tablespaces are **cluster-global** — the single most common restore failure, and
entirely preventable.

## What not to do, and what noise to ignore

- **Never** run `pg_dump` against a segment in utility mode
  (`PGOPTIONS='-c gp_session_role=utility'`) to "get a parallel dump". You get one segment's
  fragment of every table with no way to reassemble it.
- **Never** copy segment data directories with `cp`/`rsync` while the cluster is running
  and call it a backup. There is no cluster-wide checkpoint barrier; use
  `gp_create_restore_point` plus `pg_basebackup --target-gp-dbid`.
- **Never** take a `gpbackup` with `--no-history` in a schedule that later uses
  `--incremental` without `--from-timestamp`. Base selection reads the history database.
- **Never** conclude gpbackup is unavailable because it is missing from the source tree.
- Ignore the `pgbackrest` mention on
  [backup_restore (7)](https://greengagedb.org/en/docs-gg/7/backup_restore.html) unless
  someone hands you the binary: it links outside the `GreengageDB` organisation, and
  neither branch of this tree builds or ships it.
- Ignore `concourse/` — legacy Greenplum CI, including `concourse/scripts/gpdb_pitr.bash`,
  which only `concourse/tasks/gpdb_pitr.yml` invokes (`git grep gpdb_pitr` over `ci/` and
  `.github/` returns nothing). Use `make installcheck` in `src/test/gpdb_pitr/`.
- Ignore `subscriptions not dumped because current user is not a superuser`
  (`pg_dump.c:4636`) unless you actually use logical replication.

See also: [greengage-cluster-ops](../greengage-cluster-ops/SKILL.md) (mirrors, standby,
`gprecoverseg`, `gpexpand`, `gpcheckcat`),
[greengage-schema-design](../greengage-schema-design/SKILL.md) (partitioning, which decides
what `--leaf-partition-data` can do),
[greengage-data-loading](../greengage-data-loading/SKILL.md) (`COPY … ON SEGMENT`, the
mechanism `gprestore` uses), [greengage-overview](../greengage-overview/SKILL.md) (the MPP
model and the 6.x/7.x split), [greengage-testing](../greengage-testing/SKILL.md) (running
`src/test/gpdb_pitr` yourself), and
[greengage-workload-management](../greengage-workload-management/SKILL.md) (the resource
queues and groups `--with-globals` restores).
