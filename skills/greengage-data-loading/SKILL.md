---
name: greengage-data-loading
description: Load and unload Greengage in parallel, not serially through the coordinator. Covers gpfdist, readable/writable external tables, URI-to-segment mapping, gp_external_max_segs, LOG ERRORS / SEGMENT REJECT LIMIT, gp_read_error_log(), gpload YAML control files, COPY ON SEGMENT, gp_exttable_fdw, mpp_execute, s3, post-load ANALYZE. Use when a load is slow or single-threaded, when writing CREATE EXTERNAL TABLE or a gpload YAML, or on `segment reject limit reached, aborting operation` or `<SEGID> is required for file name`.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "7.x (6.x deltas noted)"
---

# Getting data into and out of Greengage

## The coordinator is the bottleneck, and that is the whole subject

`COPY sales FROM '/data/sales.csv'` does not run on the segments. It runs in what the
source calls **dispatcher mode** — `src/include/commands/copy.h` enumerates `COPY_DIRECT`,
`COPY_DISPATCH`, `COPY_EXECUTOR` and documents the middle one as "We are reading from
file/client, and forwarding all data to QEs". The coordinator opens the file, parses every
byte, hashes every row and ships each row down the interconnect — one process, one CPU,
one NIC, and adding segments makes it *slower* because the same parser feeds more
consumers. Every parallel loading mechanism in Greengage exists to bypass that path: each
segment opens its own connection to the data and parses its own slice.

| Situation | Use | Why |
|---|---|---|
| One-off, small, file is next to your `psql` | `\copy` / `COPY … FROM STDIN` | No server-side file access needed; still coordinator-serial |
| One-off, file is readable by the coordinator process | `COPY … FROM '/path'` | Simplest; coordinator-serial, so budget for it |
| Repeatable, file(s) on one or more ETL hosts, any size | **`gpfdist` + readable external table** | Every primary segment pulls its own slice over HTTP |
| Same, but you want TRUNCATE/UPDATE/MERGE and no hand-written SQL | **`gpload`** | YAML wrapper that starts gpfdist, builds the external table, stages, and merges |
| Files already pre-split onto every segment host | `file://` external table, or `COPY … ON SEGMENT` | Strict 1 URI : 1 segment — you own the splitting |
| Data in S3-compatible object storage | `s3://` custom protocol (`gpcontrib/gpcloud`) | Segments read object ranges in parallel |
| Data in another PostgreSQL/Greengage | `postgres_fdw` + `mpp_execute` | Default is coordinator-only; opt in to parallelism |
| Hive/HDFS/object stores with schema discovery | PXF — a **separate product**, own docs tree | Not in this repository |

Full syntax and option inventories: [reference/external-tables.md](reference/external-tables.md).

## gpfdist: the happy path

`gpfdist` is a small HTTP file server built from `src/bin/gpfdist/` on both lines into
`$GPHOME/bin`, on by default (`configure.in`: `PGAC_ARG_BOOL(enable, gpfdist, yes)`). It
needs `libapr-1`, `libevent` and `libyaml` (mandatory on 7.x, optional-with-a-warning on
6.x, where it only gates transformations). Run it **on the ETL host** — the point is to
keep bytes off the coordinator. Stop it with a plain `kill`; there is no `gpfdist -stop`.

```sh
gpfdist -d /data/staging -p 8081 -l /var/log/gpfdist.log &   # on the ETL host
```

```sql
CREATE READABLE EXTERNAL TABLE ext_sales (
    sale_id bigint, sale_ts timestamptz, customer text, amount numeric(12,2))
LOCATION ('gpfdist://etl1:8081/sales_*.csv')
FORMAT 'CSV' (HEADER DELIMITER ',' NULL '')
LOG ERRORS SEGMENT REJECT LIMIT 100 ROWS;

INSERT INTO sales SELECT * FROM ext_sales;   -- parallel on every segment
ANALYZE sales;                               -- mandatory, see below
```

**`gpfdist -h` no longer exists, and neither do `-q` and `-x`.** All three abort with
`The -q, -h and -x options are gone.` and exit 1 (`src/bin/gpfdist/gpfdist.c`,
`print_q_x_h_are_gone()`). Any document telling you to pass `-h` for a header row —
including `doc/src/sgml/ref/create_external_table.sgml` in this very tree — is stale. Use
the SQL `HEADER` clause: it is forwarded in the `X-GP-CSVOPT` HTTP header
(`src/backend/access/external/url.c`, `GP_CSVOPT` = `"m%1dx%3dq%3dn%1dh%1d"`), and gpfdist
skips the first line **of every file it opens** — `nextFile()` in
`src/backend/utils/misc/fstream/fstream.c` re-arms `skip_header_line` per file, so a
wildcard over 200 header-bearing CSVs is correct, not off by 199 rows.

## The URI-to-segment mapping decides your load speed

This is the fact that explains every "why is my load only using 3 segments" question.
`src/backend/access/external/external.c` (6.x: `…/external/fileam.c`) maps LOCATION URIs
onto primary segments like this:

| Protocol | Mapping | Consequence |
|---|---|---|
| `gpfdist://`, `gpfdists://` | The URI list is **duplicated round-robin until every primary segment has one**, capped at `list_length(urilocations) * gp_external_max_segs` | One URI already engages up to 64 segments |
| `file://` | Strictly **1 URI : 1 segment**, and the URI host must match that segment's `gp_segment_configuration.hostname` **or** `address` | N files ⇒ exactly N segments read |
| `http://` | Strictly **1 URI : 1 segment** | Same |
| `EXECUTE 'cmd'` | Per the `ON` clause (`ALL`, `HOST`, `HOST 'name'`, `SEGMENT n`, `COORDINATOR`, `<n>` random) | Default is every segment |
| custom (`s3://`, PXF, your own) | All participating segments; no `gp_external_max_segs` cap | |

`gp_external_max_segs` defaults to **64** (`guc_gp.c`, identical on 6.x and 7.x). On a
cluster with more than 64 primaries and a single gpfdist URI, Greengage picks 64 at random
and prints
`NOTICE:  External scan from gpfdist(s) server will utilize 64 out of 96 segment databases`.
That NOTICE is the signal to add URIs — two gpfdist instances on the same host on
different ports count as two URIs:
`LOCATION ('gpfdist://etl1:8081/sales_*.csv', 'gpfdist://etl1:8082/sales_*.csv', 'gpfdist://etl2:8081/sales_*.csv')`.
The reverse mistake errors out rather than degrading:

```
ERROR:  there are more external files (URLs) than primary segments that can read them
DETAIL:  Found 20 URLs and 3 primary segments.
```

For `file://` loads, `SELECT * FROM pg_max_external_files;` (a built-in view on both
lines, `src/backend/catalog/system_views.sql`) counts primary segments per host — the
maximum number of `file://` URIs you may place on each segment host.

**One gpfdist process is not one thread per segment.** Every segment hitting a URI shares
that process's disk and NIC — if gpfdist is CPU-bound or the ETL disk is saturated, more
URIs on the *same* host buy nothing. Move files to more hosts.

## Error handling: the error log is a file, not a table

`LOG ERRORS SEGMENT REJECT LIMIT n [ROWS|PERCENT]` turns on single-row error isolation:
malformed rows are logged and skipped instead of aborting the statement. `HandleCopyError`
(`src/backend/commands/copy.c`) re-throws anything outside errcode category
`ERRCODE_DATA_EXCEPTION`, so it catches **format** errors only — bad column counts,
unparseable values, invalid encoding — while a constraint violation still aborts. `COPY`
takes the same clause, and the log is keyed by the **target relation**, so a heap works too:

```sql
COPY tableless_heap FROM '/data/tableless.csv' CSV LOG ERRORS SEGMENT REJECT LIMIT 10;
-- NOTICE:  found 2 data formatting errors (2 or more input rows), rejected related input data

SELECT relname, filename, linenum, errmsg, rawdata FROM gp_read_error_log('tableless_heap');
SELECT gp_truncate_error_log('tableless_heap');
```

Rules the grammar enforces (`src/backend/parser/gram.y`, `OptSingleRowErrorHandling`):

| Rule | Error if violated |
|---|---|
| ROWS limit must be ≥ 2 | `invalid (ROWS) reject limit. Should be 2 or larger` |
| PERCENT limit must be 1–100 | `invalid PERCENT value. Should be (1 - 100)` |
| PERCENT is not counted until `gp_reject_percent_threshold` rows have been processed — default **300** | Silent: a 200-row file with 100% bad rows never trips a PERCENT limit |
| The first `gp_initial_bad_row_limit` rows (default **1000**) may not *all* be bad | `all 1000 first rows in this segment were rejected` / `DETAIL: Aborting operation regardless of REJECT LIMIT value` |
| Reject handling is illegal on a writable external table | `single row error handling may not be used with a writable external table` (6.x capitalises it: `Single row error handling …`) |

When the limit is exceeded you get, per segment (6.x, on PostgreSQL 9.4, drops the `type`:
`invalid input syntax for integer:`):

```
ERROR:  segment reject limit reached, aborting operation
DETAIL:  Last error was: invalid input syntax for type integer: "error_1", column i  (seg0 slice1 …)
CONTEXT:  External table exttab_basic_3, line 7 of file://…/exttab_more_errors.data, column i
```

**`LOG ERRORS INTO <table>` is dead on both lines.** The grammar accepts it only to raise
`ERROR: error table is not supported` with
`HINT: Set gp_ignore_error_table to ignore the [INTO error-table] clause for backward compatibility.`
`SET gp_ignore_error_table = on` (default `off`) downgrades that to a WARNING and ignores
the clause — the errors go to the internal log either way, so delete the `INTO` clause
instead of setting the GUC. `gpMgmt/demo/gpfdist_transform/dblp/external.sql` in this tree
still uses `log errors into dblp_errortable`; that demo does not run as written.

### Persistent error logs — the one real 6.x/7.x split

`LOG ERRORS PERSISTENTLY` keeps the log after the external table is dropped. Both lines
parse it (`ExtLogErrorTable: … | LOG_P ERRORS PERSISTENTLY`); the reader functions differ:

| | 6.x | 7.x |
|---|---|---|
| `gp_read_error_log()`, `gp_truncate_error_log()` | Built in (`src/include/catalog/pg_proc.sql`, OIDs 7076/7069) | Built in (`src/include/catalog/pg_proc.dat`, same OIDs) |
| `gp_read_persistent_error_log()`, `gp_truncate_persistent_error_log()` | **Not built in.** Installed by running `$GPHOME/share/postgresql/contrib/gpexterrorhandle.sql` (`gpcontrib/gp_error_handling/`) — there is no `.control` file, so `CREATE EXTENSION gp_error_handling` does **not** work | Built in (`pg_proc.dat`, OIDs 7080/7081). Nothing to install |

Logs are files on each segment, not relations: `<datadir>/errlog/<dbid>_<relid>` and
`<datadir>/errlogpersistent/<dbid>_<namespace_oid>_<relname>` (`src/backend/cdb/cdbsreh.c`).
They are not WAL-logged and not backed up. `gp_truncate_error_log('*')` clears the
current database (database owner); `gp_truncate_error_log('*.*')` clears every database
and requires superuser — otherwise `must be superuser to delete all error log files`.

## gpload: use it for MERGE, not for speed

`gpload` (`gpMgmt/bin/gpload.py`) is not faster than gpfdist — it *is* gpfdist. It earns
its keep for the surrounding choreography: start gpfdist on a free port, create the
external table, TRUNCATE or stage, run an UPDATE/MERGE, drop everything, in one
transaction. Reach for it for **UPDATE/MERGE loads and trickle loads with
`REUSE_TABLES`**; use plain gpfdist for a straight append where you want to see the SQL.

```yaml
---
VERSION: 1.0.0.1
DATABASE: analytics
HOST: cdw
GPLOAD:
  INPUT:
    - SOURCE:
        LOCAL_HOSTNAME: [etl1]
        PORT_RANGE: [8081, 8090]
        FILE: [/data/staging/sales_*.csv]
    - FORMAT: csv
    - HEADER: true
    - ERROR_LIMIT: 100
    - LOG_ERRORS: true
  OUTPUT:
    - TABLE: public.sales
    - MODE: merge
    - MATCH_COLUMNS: [sale_id]
    - UPDATE_COLUMNS: [amount]
    - UPDATE_CONDITION: 'amount > 0'
  PRELOAD:
    - REUSE_TABLES: true
  SQL:
    - AFTER: "ANALYZE public.sales"
```

`gpload -f sales.yml`; add `-D` to validate without loading. Facts that bite:

- **`LOG_ERRORS: true` without `ERROR_LIMIT` is a hard control-file error**:
  `gpload:input:log_errors requires gpload:input:error_limit to be specified`, and
  `error_limit must be 2 or higher`. `ERROR_TABLE` is dead but *not* rejected — gpload
  warns `ERROR_TABLE is not supported. We will set LOG_ERRORS and REUSE_TABLES to True for
  compatibility.` and silently turns both on, so a control file that sets `ERROR_TABLE`
  leaves staging tables behind. Delete it and use `LOG_ERRORS` + `gp_read_error_log()`.
- `UPDATE_CONDITION` is a bare WHERE fragment over the **target** table: gpload rewrites
  every column name it recognises to `into_table.<col>` (`fix_update_cond` in `gpload.py`)
  and ANDs it onto the `MATCH_COLUMNS` join. You cannot reference the incoming row, so
  `excluded.*`-style conditions do not exist here.
- Six control-file keys are accepted by `gpload.py` but missing from `gpMgmt/doc/gpload_help`:
  `PASSWORD`, `ERROR_PERCENT`, `FILL_MISSING_FIELDS`, `FULLY_QUALIFIED_DOMAIN_NAME`,
  `FAST_MATCH`, `STAGING_TABLE`. The `valid_tokens` table at the top of `gpload.py` is the
  authority, and it is byte-identical on 6.x and 7.x.
- `PORT_RANGE` beats a hard-coded `PORT` when loads overlap. With neither, gpload picks a
  free port between 8000 and 9000. The whole load is one transaction unless you pass
  `--no_auto_trans`.
- 7.x `gpload` is `#!/usr/bin/env python3` on `psycopg2`; 6.x is python2/3-compatible. A
  6.x-era wrapper that pins python2 will not run 7.x `gpload`.

## COPY: what Greengage adds to the PostgreSQL command

`doc/src/sgml/ref/copy.sgml` (7.x) adds `ON SEGMENT` + `FILL MISSING FIELDS` +
`[LOG ERRORS] SEGMENT REJECT LIMIT` to `COPY … FROM`, `ON SEGMENT` +
`IGNORE EXTERNAL PARTITIONS` to `COPY … TO`, and `NEWLINE 'LF'|'CR'|'CRLF'` to the options.

**`ON SEGMENT` is the only parallel form of `COPY`,** and it hands you the sharding
problem. Each segment reads or writes its own local file, so the path must contain the
literal token `<SEGID>`:

```sql
COPY sales TO   '/data/export/sales_<SEGID>.csv' ON SEGMENT CSV;
COPY sales FROM '/data/import/sales_<SEGID>.csv' ON SEGMENT CSV;
```

| Trap | Message (`src/backend/commands/copy.c`) |
|---|---|
| Path without the token | `<SEGID> is required for file name` |
| `COPY … TO STDOUT ON SEGMENT` | `STDOUT is not supported by 'COPY ON SEGMENT'` |
| `COPY … FROM STDIN ON SEGMENT` | `STDIN is not supported by 'COPY ON SEGMENT'` |
| A row in segment N's file that does not hash to segment N | `value of distribution key doesn't belong to segment with ID 0, it belongs to segment with ID 2` |

That last check is `gp_enable_segment_copy_checking` (default `on`, both lines). It is
`GUC_NO_SHOW_ALL | GUC_NOT_IN_SAMPLE`, so `SHOW ALL` will not list it. Turning it off to
force a load through corrupts distribution and every subsequent join silently produces
wrong results — never do it. Re-export with `COPY … TO … ON SEGMENT` from a cluster of
the same width, or load through gpfdist and let Greengage redistribute.

## Other protocols and FDWs

The per-protocol matrix is in [reference/external-tables.md](reference/external-tables.md).
The three facts that change what you type:

- **The s3 protocol ships no extension.** `gpcontrib/gpcloud` has no `.control` file, so
  `CREATE EXTENSION gpcloud` does not exist. Register it by hand with
  `CREATE PROTOCOL s3 (readfunc=…, writefunc=…)` over `$libdir/gpcloud.so`'s `s3_import`
  and `s3_export`, exactly as `gpcontrib/gpcloud/regress/input/0_00_prepare_protocols.source`
  does, then test the config with the `gpcheckcloud` binary before touching SQL.
- **`mpp_execute` defaults to coordinator-only.** It accepts `any`, `master`,
  `coordinator` (7.x only) and `all segments` (`src/backend/foreign/foreign.c`); anything
  else is `"<value>" is not a valid mpp_execute value`. Unset means
  `FTEXECLOCATION_COORDINATOR` (7.x) / `FTEXECLOCATION_MASTER` (6.x), so an FDW you did
  not configure runs on one node. Settable on the FDW, server or table — most specific
  wins (`doc/src/sgml/ref/create_foreign_table.sgml`) — but not on a `USER MAPPING`, and
  `ALTER FOREIGN DATA WRAPPER … OPTIONS` refuses to change it:
  `"mpp_execute" of foreign data wrapper is not allowed to be altered`. With
  `mpp_execute 'all segments'`, `file_fdw` honours `<SEGID>` in `filename` (both lines,
  `contrib/file_fdw/file_fdw.c`), which is the parallel form.
- **gpfdist and http external tables need a role attribute**, not just table privileges
  (`gpcontrib/gp_exttable_fdw/option.c`):

```sql
ALTER ROLE loader CREATEEXTTABLE (type='readable', protocol='gpfdist');
ALTER ROLE loader CREATEEXTTABLE (type='writable', protocol='gpfdist');
```

Defaults are `type='readable'`, `protocol='gpfdist'`; valid protocols are `gpfdist`,
`gpfdists`, `http`. Writable `http` does not exist. Without the attribute you get
`permission denied: no privilege to create a readable gpfdist(s) external table`.
`file://` needs superuser outright; `EXECUTE` needs superuser plus
`gp_external_enable_exec` (default on, but `PGC_POSTMASTER`, so changing it costs a restart).

### 7.x: your external table is a foreign table

7.x `initdb` runs `CREATE EXTENSION gp_exttable_fdw;` unconditionally
(`src/bin/initdb/initdb.c`) and rewrites `CREATE EXTERNAL TABLE` into
`CREATE FOREIGN TABLE … SERVER gp_exttable_server` (`src/backend/commands/exttablecmds.c`).
So on 7.x: `\d ext_sales` prints `Foreign table "public.ext_sales"` with an `FDW options:`
line instead of the 6.x `External table` block; `pg_class.relkind` is `'f'`, and the
`relstorage` column is gone from `pg_class` entirely, so a 6.x-era query filtering on
`relstorage = 'x'` (`RELSTORAGE_EXTERNAL`) fails with `column "relstorage" does not exist`;
`pg_exttable` survives only as a view over a function. `DROP EXTERNAL TABLE` still parses,
and you may skip the sugar with `CREATE FOREIGN TABLE … SERVER gp_exttable_server
OPTIONS (format 'csv', location_uris '…', …)` — `format` plus exactly one of
`location_uris` / `command` is required.

## Unloading

```sql
-- Parallel: N URIs => N output files, segment i writes to URI (i % N)
CREATE WRITABLE EXTERNAL TABLE ext_sales_out (LIKE sales)
LOCATION ('gpfdist://etl1:8081/out/sales_1.csv', 'gpfdist://etl1:8082/out/sales_2.csv')
FORMAT 'CSV' DISTRIBUTED BY (sale_id);

INSERT INTO ext_sales_out SELECT * FROM sales WHERE sale_ts >= date '2026-01-01';
```

The modulo is literal: `int my_url = segindex % num_urls;`
(`gpcontrib/gp_exttable_fdw/extaccess.c`; 6.x `src/backend/access/external/fileam.c`).
More URIs than segments is an error — `external table has more URLs than available
primary segments that can write into them`. Rows from many segments interleave inside one
output file; if you need ordering, sort after export, not during. `DISTRIBUTED BY` here
controls which segment *computes* each row, not the file layout — use it to avoid a
redistribution motion when the source table shares the key. `COPY sales TO '/tmp/sales.csv'`
writes one file on the **coordinator** and funnels every row through it;
`COPY … TO … ON SEGMENT` writes per-segment files with `<SEGID>`.

## After the load: three things people skip

**1. ANALYZE. Always.** `gp_autostats_mode` boots as `none` on both lines and 7.x does not
override it — the setting is absent from 7.x `postgresql.conf.sample`, while 6.x ships
`gp_autostats_mode=on_no_stats` there. So on a stock 7.x cluster a freshly loaded table
has `relpages = 0, reltuples = 0`, the planner thinks it is tiny, and you get broadcast
motions and nested loops over billions of rows. Even under `on_no_stats`, autostats fires
only for CTAS and for `INSERT`/`COPY` into a relation that *still* has no stats
(`src/backend/postmaster/autostats.c`, `autostats_on_no_stats_check`) — the second load
into the same table triggers nothing.

```sql
ANALYZE sales;
SELECT * FROM gp_toolkit.gp_stats_missing WHERE smischema = 'public';
```

For large partitioned tables use `analyzedb -d <db> -s <schema>`: it analyzes only what
changed since its last run and defaults to `-p 5` tables in parallel.

**2. VACUUM does something different on append-optimized tables.** A pure append load
needs no VACUUM. After UPDATE/DELETE, `VACUUM` on an AO table *rewrites* segment files
rather than reclaiming slots in place, and skips any segment file whose dead-row ratio is
below `gp_appendonly_compaction_threshold` (default **10** percent, both lines).
`VACUUM FULL` on a large AO table is almost never what you want. Storage layout belongs to
[greengage-schema-design](../greengage-schema-design/SKILL.md).

**3. Check the skew you just created.** A load is the moment distribution goes wrong.

```sql
SELECT gp_segment_id, count(*) FROM sales GROUP BY 1 ORDER BY 1;

-- skccoeff is (stddev/mean)*100 over per-segment row counts: a PERCENTAGE, 0 = perfect
SELECT skcnamespace, skcrelname, skccoeff FROM gp_toolkit.gp_skew_coefficients WHERE skcrelname = 'sales';
```

## What not to do, and what noise to ignore

- **Do not run gpfdist on the coordinator host** for a production load. It works, and it
  puts the traffic back on the node you were trying to spare.
- **Do not use `file://` to "go parallel" without pre-splitting.** One file is one segment.
- **Do not add URIs on one ETL host past that host's disk or NIC.** The segment count in
  the `will utilize N out of M` NOTICE is a ceiling, not a throughput promise.
- **Do not set `gp_ignore_error_table = on`** to revive `LOG ERRORS INTO`, and **do not
  turn off `gp_enable_segment_copy_checking`** to force a `COPY … ON SEGMENT` through.
  The first hides nothing useful; the second produces silent wrong answers later.
- **Ignore `\d` cosmetic differences** between the lines — a 7.x external table showing as
  `Foreign table` is normal, not a mis-created object.
- **Ignore the `-t` range in `gpMgmt/doc/gpfdist_help`.** It says 2–600; the binary
  enforces `Error: -t timeout must be between 2 and 7200, or 0 for no timeout`.
- A load that dies with `gpfdist server closed connection` plus
  `HINT: The root cause is likely to be an overload of the ETL host or a temporary network
  glitch …` is an ETL-host capacity problem, not a database problem. **Do not reach for
  `gpfdist_retry_timeout`** — it is set on the curl handle only `if (forwrite)`
  (`url_curl.c`), so it governs *unload* POSTs and has no effect on a read. Fix the ETL
  host, or set `readable_external_table_timeout` if you want reads to fail fast.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `there are more external files (URLs) than primary segments that can read them` | More LOCATION URIs than primaries | Reduce URIs, or use fewer/larger files behind one gpfdist |
| `NOTICE: External scan … will utilize 64 out of N segment databases` | `list_length(URIs) * gp_external_max_segs` < primaries | Add URIs (more gpfdist ports/hosts); raising `gp_external_max_segs` moves the cap but not the ETL host's disk |
| `segment reject limit reached, aborting operation` | Bad rows exceeded the limit on one segment | Read `gp_read_error_log()`, fix the source, or raise the limit |
| `all 1000 first rows in this segment were rejected` | `gp_initial_bad_row_limit` guard fired | Wrong FORMAT/DELIMITER/ENCODING almost always — check the first data line, not the limit |
| `error table is not supported` | `LOG ERRORS INTO <table>` | Remove `INTO <table>`; use `gp_read_error_log()` |
| `line too long in file <name> near (N bytes)` | Row exceeds gpfdist's `-m` (default 32768) | Restart gpfdist with a larger `-m`; the ceiling is 256MB only in a libyaml (`GPFXDIST`) build — mandatory on 7.x, optional on 6.x, where a build without it caps `-m` at 1MB |
| `connection with gpfdist failed for "…", effective url: "…"` | Segment host cannot reach the ETL host/port | Segments, not the coordinator, open these connections — check firewalls from every segment host |
| `http response code 404 from gpfdist (…)` | Path is not under gpfdist's `-d`, or the wildcard matched nothing | gpfdist serves relative to `-d`; `/` as `-d` is refused outright |
| `segment has not received data from gpfdist for long time, cancelling the query.` | `readable_external_table_timeout` (default 0 = off) was set and elapsed | Only meaningful if you set it; otherwise look at the ETL host |
| `must be superuser to create an external table with a file protocol` | `file://` needs superuser | Use `gpfdist://`, or grant the load role `CREATEEXTTABLE` and switch protocol |
| `permission denied: no privilege to create a readable gpfdist(s) external table` | Role lacks the attribute | `ALTER ROLE r CREATEEXTTABLE (type='readable', protocol='gpfdist');` |
| `<SEGID> is required for file name` | `COPY … ON SEGMENT` without the token | Put `<SEGID>` in the path |
| Load finished, next query plans terribly | No statistics — `gp_autostats_mode = none` | `ANALYZE <table>`, then check `gp_toolkit.gp_stats_missing` |
| One segment takes 10x as long | Distribution skew introduced by the load | `SELECT gp_segment_id, count(*) …`; see [greengage-schema-design](../greengage-schema-design/SKILL.md) |

See also: [greengage-schema-design](../greengage-schema-design/SKILL.md),
[greengage-query-performance](../greengage-query-performance/SKILL.md),
[greengage-cluster-ops](../greengage-cluster-ops/SKILL.md),
[greengage-backup-restore](../greengage-backup-restore/SKILL.md),
[greengage-overview](../greengage-overview/SKILL.md), [greengage-debug](../greengage-debug/SKILL.md).
