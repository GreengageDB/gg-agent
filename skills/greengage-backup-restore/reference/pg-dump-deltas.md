# `pg_dump` / `pg_dumpall` / `pg_restore`: what Greengage changes

All three are built from `src/bin/pg_dump/` on both branches (`pg_dump.c`, `pg_dumpall.c`,
`pg_restore.c`; 7.x adds the Greengage-only `dumputils_gp.c`, which 6.x does not have).
**Every `file:line` below is 7.x** unless a 6.x number is given beside it. Documented at
[pg_dump](https://greengagedb.org/en/docs-gg/current/reference/utils/pg_dump.html),
[pg_dumpall](https://greengagedb.org/en/docs-gg/current/reference/utils/pg_dumpall.html),
[pg_restore](https://greengagedb.org/en/docs-gg/current/reference/utils/pg_restore.html).

## The structural limit

Every byte flows coordinator → client. From
[backup_restore (7)](https://greengagedb.org/en/docs-gg/7/backup_restore.html): "All data
is streamed through the coordinator instance and written to its file system or standard
output" and "The coordinator must have enough local disk space to store the full backup."

`pg_dump -j N` opens `N + 1` connections, all to the coordinator. `-j` also requires the
directory format (`archiveFormat != archDirectory && numWorkers > 1` is rejected with
`parallel backup only supported by the directory format`, `pg_dump.c:852`; 6.x `:753`,
where it is an `exit_horribly`). The docs put it flatly: parallel dumps "are parallelized
only on the query dispatcher (master) node, not across the query executor (segment) nodes
as is the case when you use `gpbackup`." `gpbackup` is the only tool that makes segments
write their own data.

## Greengage-only options in `pg_dump`

| Option | Effect | Source |
|---|---|---|
| `--gp-syntax` | Emit the distribution clause (`DISTRIBUTED BY (...)`, `DISTRIBUTED RANDOMLY`, `DISTRIBUTED REPLICATED`) in `CREATE TABLE`. Default when the server is Greengage | `pg_dump.c:486`, `usage()` |
| `--no-gp-syntax` | Suppress it, producing SQL a plain PostgreSQL server accepts. Default when the server is PostgreSQL | `pg_dump.c:487` |

Related messages:

| String | When |
|---|---|
| `options "--gp-syntax" and "--no-gp-syntax" cannot be used together` | both passed (`pg_dump.c:709`, `:718`; 6.x `:640`, `:649`). Logged as a warning, then `exit(1)` |
| `server is not a Greengage Database instance; --gp-syntax option ignored` | `--gp-syntax` against PostgreSQL (`pg_dump.c:904`). 6.x spells it `Server is not a Greengage Database instance; --gp-syntax option ignored.` (`:805`) — capital `S`, trailing period |

**Without `--gp-syntax` against a Greengage server you still get the clause** — it is the
default there. Pass `--no-gp-syntax` deliberately when the target is PostgreSQL; restoring
a distribution clause into PostgreSQL is a syntax error.

## Silent behaviour you should know about

| Behaviour | Source |
|---|---|
| The `gp_toolkit` schema is auto-added to the exclude list when the server predates 7 (on 7.x `gp_toolkit` is an extension and is skipped as such) | `pg_dump.c:948-952` |
| `--binary-upgrade` from a version older than 6 emits `ALTER DATABASE ... SET gp_use_legacy_hashops=on`, because the hash function changed | `pg_dump.c:3613`, `makeAlterConfigCommand(conn, "gp_use_legacy_hashops=on", ...)` |
| Greengage has no user-defined triggers and no large-object facility, so `pg_restore -T/--trigger`, `-S/--superuser` and `--disable-triggers` have nothing to act on; and "Because Greengage DB does not support serializable transactions, the `--serializable-deferrable` option has no effect" | docs `reference/utils/pg_dump.html`, `reference/utils/pg_restore.html` |

## Greengage-only options in `pg_dumpall`

| Option | Effect | Source |
|---|---|---|
| `--resource-queues` | Dump resource queue definitions | `pg_dumpall.c:142` (6.x `:134`) |
| `--resource-groups` | Dump resource group definitions | `pg_dumpall.c:143` (6.x `:135`) |
| `--gp-syntax` / `--no-gp-syntax` | Passed through to each `pg_dump`; **`--gp-syntax` implies `--resource-queues` and `--resource-groups`** | `pg_dumpall.c:368-371` (6.x `:336-339`) |

The `-r` trap: in PostgreSQL `-r` means `--roles-only`; in Greengage's lineage it meant
resource queues. **The docs page still lists `-r | --roles-only`, but the binary refuses
the short form outright:**

```
-r option is not supported. Did you mean --roles-only or --resource-queues?
```

(`pg_dumpall.c:286`; identical at `pg_dumpall.c:274` on 6.x.) Spell out the long option.

The dump header is `-- Greengage Database cluster dump` (`pg_dumpall.c:582`; 6.x `:507`) —
a quick way to tell a Greengage cluster dump from a PostgreSQL one. The footer is still
upstream's `-- PostgreSQL database cluster dump complete`, so do not key on that.

## Globals are cluster-wide and `pg_dump` never carries them

`pg_dump` dumps one database. Roles, tablespaces, resource queues and resource groups live
in shared catalogs and only `pg_dumpall` sees them. A restore into a fresh cluster fails on
every `ALTER ... OWNER TO` and `GRANT` unless the roles are there first.

```sh
pg_dumpall --globals-only > globals.sql                      # roles + tablespaces
pg_dumpall --roles-only   > roles.sql                        # roles only
pg_dumpall --tablespaces-only > tablespaces.sql
pg_dumpall --resource-queues --resource-groups > wlm.sql     # workload management
psql -f globals.sql postgres                                 # run first, on the target
```

`gpbackup` includes globals by default (`--without-globals` opts out) but `gprestore`
restores them only with `--with-globals`.

## Useful invocations

```sh
# Schema of one schema, portable to PostgreSQL
pg_dump --no-gp-syntax -s --schema=sales marketplace > sales_schema.sql

# One table with its Greengage storage and distribution clauses
pg_dump --gp-syntax -s --table=sales.orders marketplace

# Custom format, restored in parallel (still all through the coordinator)
pg_dump -Fc --dbname=marketplace -f marketplace.dump
pg_restore -j 8 --dbname=restored_db marketplace.dump

# Directory format, parallel dump
pg_dump -Fd -j 8 -f /backup/marketplace.d marketplace
```

## Version and psql deltas that bite here

| | 6.x | 7.x |
|---|---|---|
| PostgreSQL base | 9.4.26 | 12.22 |
| `psql \gexec` | **does not exist** (`git grep '"gexec"' src/bin/psql` returns nothing) | exists (`command.c:341`) |
| Recovery settings file | `recovery.conf` (`xlog.c:87`) | `postgresql.conf` + `recovery.signal` |
| Data-dir env var | `MASTER_DATA_DIRECTORY` | `COORDINATOR_DATA_DIRECTORY` |

A 6.x dump restored into a 7.x cluster is a **migration**, not a restore: the catalog,
partitioning syntax and default hash operator class all differ. See
[Migrate from Greenplum](https://greengagedb.org/en/docs-gg/current/migrate_from_gp.html).
