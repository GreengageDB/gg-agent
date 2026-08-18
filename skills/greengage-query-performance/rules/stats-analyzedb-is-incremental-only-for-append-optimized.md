---
title: Expect analyzedb to re-analyze every heap table on every run
impact: HIGH
impactDescription: "analyzedb's incremental skip applies only to append-optimized tables; on a heap-only warehouse it is plain parallel ANALYZE and the nightly window does not shrink"
tags: [query-performance, statistics, analyzedb, utilities]
---

## Expect `analyzedb` to re-analyze every heap table on every run

**Impact: HIGH**

`analyzedb` is the incremental, parallel statistics driver, and its own `--help` text is
unusually blunt about the limit:

> 'Incremental' means if a table or partition has not been modified by DML or DDL commands
> since the last analyzedb run, it will be automatically skipped since its statistics must
> be up to date. Some restrictions apply: 1. The incremental semantics only applies to
> append-only tables or partitions. **All heap tables are regarded as having stale stats
> every time analyzedb is run.** This is because we use AO metadata to check for DML or DDL
> events, which is not available to heap tables. 2. Views, indices and external tables are
> automatically skipped.

The mechanism confirms it: `gpMgmt/bin/analyzedb` collects a `modcount` per append-optimized
table by summing `modcount` from the table's `pg_aoseg` relation via `gp_dist_random()`, and
compares it against the state file from the previous run. Heap tables have no such counter,
so the code marks all of them dirty unconditionally. State lives under
`$COORDINATOR_DATA_DIRECTORY/db_analyze/<dbname>/<timestamp>/` (`$MASTER_DATA_DIRECTORY` on
6.x).

The flags that matter, from the utility's own parser:

| Flag | Meaning |
|---|---|
| `-d <db>` | database. Required. |
| `-s <schema>` / `-t <schema>.<table>` | limit to a schema or one table. `-s`, `-t` and `-f` are mutually exclusive |
| `-i <cols>` / `-x <cols>` | include or exclude columns. Mutually exclusive, and **only valid together with `-t`** — otherwise `option -i or -x can only be used together with -t` |
| `-f <file>` | a config file listing qualified table names, one per line |
| `-l`, `--list` | dry run: print what would be analyzed |
| `-p <n>` | tables analyzed in parallel, 1-10, **default 5** |
| `--full` | ignore incrementality; analyze everything requested |
| `--skip_orca_root_stats` | do not generate root-partition statistics for GPORCA |
| `--clean_last`, `--clean_all` | delete state files from the last run, or all of them |
| `-a` | do not prompt for confirmation |

**Incorrect (expecting incremental behaviour on a heap warehouse):**

```bash
# Bad: every table here is heap, so this is a full ANALYZE of the database
# every night, and the "incremental" label explains nothing about the runtime.
analyzedb -d dw -a
```

**Correct (scope it, and see what it will actually do before it does it):**

```bash
# Good: dry-run first, so the work is visible rather than assumed.
analyzedb -d dw -s analytics -l

# Then run it, scoped and parallel.
analyzedb -d dw -s analytics -p 8 -a
```

```bash
# Good: after loading one partition, analyze only that table.
analyzedb -d dw -t analytics.orders -a
```

Check whether the incremental path can apply at all before you rely on it — count how many
of the tables in scope are append-optimized:

```sql
-- 7.x: storage is a table access method
SELECT am.amname, count(*) AS tables
FROM   pg_class c
JOIN   pg_namespace n ON n.oid = c.relnamespace
LEFT   JOIN pg_am am  ON am.oid = c.relam
WHERE  n.nspname = 'analytics' AND c.relkind = 'r'
GROUP  BY am.amname;
-- heap      | 412     <- analyzedb re-analyzes all of these every run
-- ao_column |  17
```

On 6.x use `pg_appendonly` instead, since `pg_class.relam` is only meaningful for indexes:

```sql
-- 6.x
SELECT (pa.relid IS NOT NULL) AS append_optimized, count(*) AS tables
FROM   pg_class c
JOIN   pg_namespace n ON n.oid = c.relnamespace
LEFT   JOIN pg_appendonly pa ON pa.relid = c.oid
WHERE  n.nspname = 'analytics' AND c.relkind = 'r'
GROUP  BY 1;
```

For a heap-heavy schema, plain `ANALYZE` driven by your own change log is often the better
tool — you know which tables the ETL touched, and `analyzedb` does not. Reach for
`analyzedb` when the schema is append-optimized (where the skip is real) or when you want
its parallelism and per-partition handling.

Reference: [Greengage DB utility: analyzedb](https://greengagedb.org/en/docs-gg/current/reference/utils/analyzedb.html)
