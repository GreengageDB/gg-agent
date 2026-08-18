# Point-in-time recovery: the grounded flow

Everything here is derived from `src/test/gpdb_pitr/test_gpdb_pitr.sh` on
`refs/remotes/origin/7.x`, the only end-to-end PITR procedure that exists in the Greengage
tree. Run it with `make installcheck` in `src/test/gpdb_pitr/`. (`concourse/scripts/gpdb_pitr.bash`
also drives it, but only from the legacy Concourse pipelines — nothing under `ci/` or
`.github/` references it.) Do not extrapolate beyond it.

There is **no PITR utility**. You script the steps below.

## Where the pieces live

| Piece | 7.x | 6.x |
|---|---|---|
| `gp_create_restore_point(restore_point_name text)` → `(gp_segment_id smallint, restore_lsn pg_lsn)` | built in, `src/include/catalog/pg_proc.dat:11549`; implementation `src/backend/access/transam/xlogfuncs_gp.c` | `CREATE EXTENSION gp_pitr;` — `gpcontrib/gp_pitr/gp_pitr--1.1.sql`, control `default_version = '1.1'`, `relocatable = false` |
| `gp_switch_wal()` → `(gp_segment_id smallint, pg_switch_wal pg_lsn, pg_walfile_name text)` | built in, `pg_proc.dat:11553` | same extension |
| `gp_stat_archiver` | generated MPP view (`src/backend/catalog/system_views_gp.in` lists `pg_stat_archiver`) | created by the `gp_pitr` extension |
| Test suite | `src/test/gpdb_pitr/` | same, plus `test_mirror_wal_recycling` |

`gpcontrib/gp_pitr` **is absent on 7.x**. `CREATE EXTENSION gp_pitr` there fails; the
functions already exist in `pg_catalog`.

Both functions have `EXECUTE` revoked from `public` on both lines — 7.x in
`src/backend/catalog/system_views.sql:1809-1810`, 6.x in the extension SQL
(`REVOKE EXECUTE ON FUNCTION gp_create_restore_point(text) FROM public;`) — and both are
declared to run on the coordinator only (`proexeclocation => 'c'` in `pg_proc.dat`,
`EXECUTE ON MASTER` in the 6.x extension).

## 1. Turn on WAL archiving on the coordinator and every primary

```
wal_level = replica
archive_mode = on
archive_command = 'cp %p /backup/archive_seg%c/%f'
```

`wal_level = replica` is **7.x only**. 6.x's `wal_level_options` are
`minimal | archive | hot_standby | logical` (`src/backend/access/rmgrdesc/xlogdesc.c:30`),
default `archive`; `replica` there is an invalid value and the instance will not start.
7.x keeps `archive` and `hot_standby` as deprecated aliases for `replica`
(`xlogdesc.c:31-36`), so `wal_level = archive` is the spelling that works on both lines.
`archive_mode = on` is valid on both.

`%c` is a **Greengage extension** to `archive_command`, substituted with the segment
content ID (`src/backend/postmaster/pgarch.c:605`, comment `GPDB: %c: contentId of
segment`). Every segment on a host executes the same command string, so without `%c` (or
`%d` on 6.x, which is the dbid) they collide in a shared archive directory.

Complete escape set:

| Escape | `archive_command` | `restore_command` | Branch |
|---|---|---|---|
| `%p` source path, `%f` source filename, `%%` | yes | yes | both |
| `%r` last restart point filename | n/a | yes | both |
| `%c` content ID | yes | yes | both |
| `%d` dbid | yes | yes | **6.x only** |

Create the target directories on each host first, one per content ID:
`mkdir -p /backup/archive_seg{-1,0,1,2}`. Restart with `gpstop -ar` so the segments pick
the settings up.

## 2. Take a base backup of every instance

```sh
pg_basebackup -h <host> -p <port> -X stream -D <replica_dir> --target-gp-dbid <new_dbid>
```

`--target-gp-dbid` is a Greengage-only, **required** flag — it decides the dbid-numbered
subdirectory under each user tablespace. Omitting it aborts with
`no target dbid specified, --target-gp-dbid is required`
(`src/bin/pg_basebackup/pg_basebackup.c:2539`), and with tablespaces present you also see
`cannot restore user-defined tablespaces without the --target-gp-dbid option`.

Do this for the coordinator (content `-1`) and every primary. Assign each replica a dbid
that does not collide with the source cluster's `gp_segment_configuration.dbid`.

## 3. Create the distributed restore point

```sql
SELECT gp_segment_id, restore_lsn
FROM   gp_create_restore_point('nightly_2026_08_18')
ORDER  BY gp_segment_id;
```

You get one row per instance, coordinator first as `gp_segment_id = -1`.

What makes it cluster-consistent: the function takes `TwophaseCommitLock` in
`LW_EXCLUSIVE` *before* dispatching `pg_catalog.pg_create_restore_point(<name>)` to the
segments (`xlogfuncs_gp.c:91`), so no concurrent two-phase transaction can broadcast its
distributed commit-prepared record while the restore points are being written. During
recovery, transactions whose distributed commit record was already written get rebroadcast
and complete; those that had not are absent. One-phase-commit and read-only transactions
are never blocked.

Calling `pg_create_restore_point()` separately on each segment does **not** give you this
and produces a torn cluster.

## 4. Force the restore-point WAL out to the archive

`gp_create_restore_point` writes a record into the *current* WAL segment, which is not
archived until it fills or is switched. Switch it cluster-wide:

```sql
SELECT gp_segment_id, pg_switch_wal, pg_walfile_name FROM gp_switch_wal();
```

Then wait for the archiver on every instance. `gp_stat_archiver` is the cluster-wide view
of `pg_stat_archiver`, with `gp_segment_id` prepended:

```sql
SELECT gp_segment_id, last_archived_wal, last_archived_time, failed_count, last_failed_wal
FROM   gp_stat_archiver
ORDER  BY gp_segment_id;
```

Compare `last_archived_wal` per segment against the `pg_walfile_name` values that
`gp_switch_wal()` returned. The test's `check_archival()` helper polls exactly this join
every 0.2 s for up to ~10 minutes and only returns once `bool_and(seg_archived)` is true
across a hard-coded four rows — the demo cluster's coordinator plus three primaries
(`sql/gpdb_pitr_setup.sql`); use your own instance count. A nonzero `failed_count` means
`archive_command` is broken — fix it before trusting anything.

Note the CTAS restriction: `CREATE TABLE ... AS SELECT ... FROM gp_switch_wal()` fails. The
test works around it with a plpgsql cursor over `gp_switch_wal()`.

## 5. Recover the replicas to the restore point

Append to each replica's `postgresql.conf`:

```
restore_command = 'cp /backup/archive_seg%c/%f %p'
recovery_target_name = 'nightly_2026_08_18'
recovery_target_action = 'promote'
recovery_end_command = 'touch <replica_dir>/recovery_finished'
```

Empty each replica's `postgresql.auto.conf` — the source cluster's synchronous-replication
settings would otherwise make the replicas wait for mirrors that do not exist. Then
`touch <replica_dir>/recovery.signal` and start each instance with
`pg_ctl start -D <replica_dir>`.

(6.x is PostgreSQL 9.4-based and reads these settings from a `recovery.conf` file —
`RECOVERY_COMMAND_FILE` at `src/backend/access/transam/xlog.c:87` — rather than from
`postgresql.conf` plus `recovery.signal`.)

Wait for the new coordinator to accept connections (`pg_isready`).

## 6. Rewrite the recovered cluster's topology

The recovered coordinator still carries the *source* cluster's
`gp_segment_configuration`, including mirrors that do not exist. Fix it in utility mode:

```sh
PGOPTIONS="-c gp_session_role=utility" psql postgres -c "
SET allow_system_table_mods = true;
DELETE FROM gp_segment_configuration WHERE preferred_role = 'm';
UPDATE gp_segment_configuration SET dbid = 10, datadir = '<replica_m>'  WHERE content = -1;
UPDATE gp_segment_configuration SET dbid = 11, datadir = '<replica_p1>' WHERE content = 0;
UPDATE gp_segment_configuration SET dbid = 12, datadir = '<replica_p2>' WHERE content = 1;
UPDATE gp_segment_configuration SET dbid = 13, datadir = '<replica_p3>' WHERE content = 2;
"
```

`PGOPTIONS='-c gp_session_role=utility'` is the portable utility-mode spelling — it works
on 6.x and on 7.x, where `guc.c:4761` keeps it as a rename alias onto `gp_role`.
`gp_role=utility` is 7.x-only. The dbid values must match the `--target-gp-dbid` you passed
to `pg_basebackup`.

Then point the environment at the recovered coordinator and restart through the normal
tooling so the MPP layer comes up:

```sh
export COORDINATOR_DATA_DIRECTORY=<replica_m>   # 6.x: MASTER_DATA_DIRECTORY
gpstop -ar
```

## 7. Validate

The test asserts the four distributed-commit cases (`sql/gpdb_pitr_validate.sql`):

- a two-phase `DELETE` that reached the restore point **before** the lock was acquired is
  *not* replayed;
- a two-phase `DELETE` whose distributed commit record was already written **is**
  rebroadcast during recovery;
- an `INSERT` committed after the restore point is gone;
- a one-phase commit before the restore point is present.

Run your own equivalents. Then check row counts, per segment
(`SELECT gp_segment_id, count(*) FROM t GROUP BY 1`), and run `gpcheckcat`.

## Errors and what they mean

| Error | Cause |
|---|---|
| `cannot use gp_create_restore_point() when not in QD mode` | `xlogfuncs_gp.c:79` — dispatched to a segment, run in utility mode, or pushed into a CTAS/`gp_dist_random` |
| `cannot use gp_switch_wal() when not in QD mode` | `xlogfuncs_gp.c:215`, same causes |
| `function with EXECUTE ON restrictions cannot be used in the SELECT list of a query with FROM` | the function was placed in the target list of a query that has a `FROM` clause; put it in `FROM` |
| `permission denied for function gp_create_restore_point` | `EXECUTE` is revoked from `public`; grant explicitly or use a superuser |
| `no target dbid specified, --target-gp-dbid is required` | `pg_basebackup` without the Greengage flag |

Reference:
[Backup and restore](https://greengagedb.org/en/docs-gg/current/backup_restore.html) and
[Backup and restore (7)](https://greengagedb.org/en/docs-gg/7/backup_restore.html)
