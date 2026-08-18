# External tables, gpfdist and gpload — full inventory

Lookup material only. Method lives in [SKILL.md](../SKILL.md). Everything below was read
from `refs/remotes/origin/7.x` and `refs/remotes/origin/6.x` of `GreengageDB/greengage`.
Where a row says nothing about versions, 6.x and 7.x agree.

## CREATE EXTERNAL TABLE — full syntax (7.x)

From `doc/src/sgml/ref/create_external_table.sgml`, corrected against
`src/backend/parser/gram.y` where the man page lags (noted inline).

```sql
CREATE [READABLE] EXTERNAL [TEMPORARY | TEMP] TABLE table_name
    ( column_name data_type [, ...] | LIKE other_table )
    LOCATION ('file://seghost[:port]/path/file' [, ...])
      | ('gpfdist://filehost[:port]/file_pattern[#transform=name]'
      |  'gpfdists://filehost[:port]/file_pattern[#transform=name]' [, ...])
    FORMAT 'TEXT'  [( format_options )]
         | 'CSV'   [( format_options )]
         | 'CUSTOM' (formatter=<function>)
    [ OPTIONS ( key 'value' [, ...] ) ]
    [ ENCODING 'encoding' ]
    [ [LOG ERRORS [PERSISTENTLY]] SEGMENT REJECT LIMIT count [ROWS | PERCENT] ]

CREATE [READABLE] EXTERNAL WEB [TEMPORARY | TEMP] TABLE table_name
    ( column_name data_type [, ...] | LIKE other_table )
    LOCATION ('http://webhost[:port]/path/file' [, ...])
  | EXECUTE 'command' [ ON ALL
                      | ON COORDINATOR          -- 7.x; ON MASTER on both lines
                      | ON <number_of_segments>
                      | ON HOST ['segment_hostname']
                      | ON SEGMENT <segment_id> ]
    FORMAT … [ OPTIONS … ] [ ENCODING … ]
    [ [LOG ERRORS [PERSISTENTLY]] SEGMENT REJECT LIMIT count [ROWS | PERCENT] ]

CREATE WRITABLE EXTERNAL [TEMPORARY | TEMP] TABLE table_name
    ( column_name data_type [, ...] | LIKE other_table )
    LOCATION ('gpfdist://outputhost[:port]/filename[#transform=name]'
            | 'gpfdists://outputhost[:port]/filename[#transform=name]' [, ...])
    FORMAT … [ OPTIONS … ] [ ENCODING 'write_encoding' ]
    [ DISTRIBUTED BY (column [opclass], [ ... ]) | DISTRIBUTED RANDOMLY ]

CREATE WRITABLE EXTERNAL WEB [TEMPORARY | TEMP] TABLE table_name
    ( column_name data_type [, ...] | LIKE other_table )
    EXECUTE 'command' [ON ALL]
    FORMAT … [ OPTIONS … ] [ ENCODING 'write_encoding' ]
    [ DISTRIBUTED BY (column [opclass], [ ... ]) | DISTRIBUTED RANDOMLY ]
```

The SGML synopsis omits `PERSISTENTLY`; the grammar has it
(`ExtLogErrorTable: OptLogErrorTable | LOG_P ERRORS PERSISTENTLY`).

### `ON` clause values (`gram.y`, `ext_on_clause_item`)

| Clause | Internal DefElem | 6.x | 7.x |
|---|---|---|---|
| `ON ALL` | `all` | yes | yes |
| `ON HOST` | `eachhost` (one segment per host) | yes | yes |
| `ON HOST 'name'` | `hostname` | yes | yes |
| `ON MASTER` | `master` (6.x) / `coordinator` (7.x) | yes | yes |
| `ON COORDINATOR` | `coordinator` | **no** | yes |
| `ON SEGMENT <n>` | `segment` | yes | yes |
| `ON <n>` | `random` — n randomly chosen segments | yes | yes |

`ON COORDINATOR` / `ON MASTER` with a `LOCATION` clause is rejected for every built-in
protocol: 7.x raises `'ON COORDINATOR' is not supported by this protocol yet`
(`src/backend/access/external/external.c`), 6.x raises
`'ON MASTER' is not supported by this protocol yet` (`src/backend/optimizer/plan/createplan.c`).
It is allowed for custom protocols (`s3://` uses it in `gpcontrib/gpcloud/regress/`).

### FORMAT options

| Option | TEXT | CSV | Notes |
|---|---|---|---|
| `HEADER` | read only | read only | Forwarded to gpfdist via `X-GP-CSVOPT`; skipped once per file. On a readable table you also get `NOTICE: HEADER means that each one of the data files has a header row`; on a writable one it is an error: `HEADER is not yet supported for writable external tables` (`exttablecmds.c`) |
| `DELIMITER [AS] 'c'` / `'OFF'` | yes | yes | Default tab in TEXT, comma in CSV. `'OFF'` is legal in **both** formats but only on an external table with exactly one column — plain `COPY` raises `using no delimiter is only supported for external tables` (`copy.c`), a multi-column external table `using no delimiter is only possible for a single column table` (`exttablecmds.c`) |
| `NULL [AS] 'string'` | yes | yes | Default `\N` in TEXT, empty in CSV |
| `ESCAPE [AS] 'c'` / `'OFF'` | yes (`'OFF'` allowed) | single char only | Default `\` in TEXT, `"` in CSV. `ESCAPE 'OFF'` is **TEXT-only**: CSV raises `COPY escape in CSV format must be a single character` |
| `QUOTE [AS] 'c'` | — | yes | Default `"` |
| `FORCE NOT NULL col [, …]` | — | read | |
| `FORCE QUOTE col [, …]` | — | write | |
| `NEWLINE [AS] 'LF'` / `'CR'` / `'CRLF'` | read | read | Autodetected from the first row if omitted |
| `FILL MISSING FIELDS` | read | read | Missing trailing columns become NULL instead of an error |

`FORMAT 'CUSTOM' (formatter=<fn>)` uses a user formatter; `contrib/formatter` and
`contrib/formatter_fixedwidth` ship examples on both lines.

### `OPTIONS (…)` and the 7.x FDW option names

`OPTIONS (key 'value')` passes arbitrary key/value pairs to a custom protocol or
formatter. On 7.x the same bag is what `\d` shows as `FDW options:`, and the internal
names are visible there:

```
-- verbatim from src/test/regress/output/external_table.source, line wrapped here
FDW options: (format 'text', delimiter '|', "null" E'\\N', escape E'\\',
              hello 'world', bonjour 'again', nihao 'again and again',
              location_uris 'file://<host><dir>/data/exttab_few_errors.data',
              execute_on 'ALL_SEGMENTS', log_errors 'disable',
              encoding 'UTF8', is_writable 'false')
```

`hello`/`bonjour`/`nihao` there are the user's `OPTIONS (…)` pairs: they land in the same
bag as the format and location options.

`gpcontrib/gp_exttable_fdw/option.c` requires, on a `ForeignTable`, `format`
(`must specify format option([text | csv | custom])`) plus **exactly one** of
`location_uris` and `command` — neither gives `must specify one of location_uris and
command option`, both give `location_uris and command options conflict with each other`.
`error_log_persistent 'true'` is an accepted spelling of `LOG ERRORS PERSISTENTLY`;
`reject_limit_type` (`rows`/`row`/`percentage`/`percent`) plus `reject_limit` spell
`SEGMENT REJECT LIMIT`.

## Protocols

| URI scheme | Where implemented | Read | Write | Parallelism | Privilege needed |
|---|---|---|---|---|---|
| `gpfdist://` | `src/bin/gpfdist/`, `src/backend/access/external/url_curl.c` | yes | yes | URIs duplicated to all primaries, capped at `#URIs × gp_external_max_segs` | `CREATEEXTTABLE (type=…, protocol='gpfdist')` |
| `gpfdists://` | same, `--ssl <dir>` on the server | yes | yes | same | `protocol='gpfdists'` |
| `file://` | `url_file.c` | yes | no | strict 1 URI : 1 segment; URI host must match that segment's `gp_segment_configuration.hostname` **or** `address` | **superuser** |
| `http://` | `url_curl.c` | yes | no | strict 1 URI : 1 segment | `protocol='http'` |
| `EXECUTE 'cmd'` | `url_execute.c` | yes | yes | per `ON` clause | superuser (`must be superuser to create an EXECUTE external web table`) + `gp_external_enable_exec=on` |
| custom, e.g. `s3://` | `url_custom.c` + `CREATE PROTOCOL` | depends | depends | all segments; no `gp_external_max_segs` cap | ownership of the protocol, else `SELECT` on it (readable) / `INSERT` (writable) |

`src/include/utils/uri.h` defines `URI_FILE`, `URI_FTP`, `URI_HTTP`, `URI_GPFDIST`,
`URI_CUSTOM`, `URI_GPFDISTS`. `ftp://` parses (`uriparser.c` sets `URI_FTP`) but nothing
consumes it: neither segment-mapping branch in `external.c` matches `URI_FTP`, and
`url_fopen` (`url.c`) has no FTP case. Treat `ftp://` as unsupported. Any scheme not in
that list is treated as a custom protocol name and looked up in `pg_extprotocol`.

### Custom protocols

```sql
-- Both lines. Superuser only.
CREATE [TRUSTED] PROTOCOL name (
    [readfunc='read_call_handler'] [, writefunc='write_call_handler']
    [, validatorfunc='validate_handler'] );
```

The s3 protocol from `gpcontrib/gpcloud` ships **no** `.control` file — there is no
`CREATE EXTENSION gpcloud`. Register it exactly as the regression setup does
(`gpcontrib/gpcloud/regress/input/0_00_prepare_protocols.source`):

```sql
CREATE OR REPLACE FUNCTION read_from_s3() RETURNS integer
    AS '$libdir/gpcloud.so', 's3_import' LANGUAGE C STABLE;
CREATE OR REPLACE FUNCTION write_to_s3() RETURNS integer
    AS '$libdir/gpcloud.so', 's3_export' LANGUAGE C STABLE;
CREATE PROTOCOL s3 (readfunc = read_from_s3, writefunc = write_to_s3);

CREATE READABLE EXTERNAL TABLE s3_sales (…)
LOCATION('s3://s3-us-west-2.amazonaws.com/bucket/prefix/ config=/home/gpadmin/s3.conf')
FORMAT 'csv';
```

`gpcontrib/gpcloud/bin/gpcheckcloud/` builds `gpcheckcloud`, which validates the config
file and lists the objects a URL would match, without touching the database.

`contrib/extprotocol` is the worked example for writing your own; it is in `ICW_TARGETS`
on both lines, so it is exercised by `make installcheck-world`.

## gpfdist flags

Authority is the option table in `src/bin/gpfdist/gpfdist.c` plus the range checks a few
lines below it. `gpMgmt/doc/gpfdist_help` understates the ranges of `-t` (it says 2–600)
and `-w` (it says max 600), and does not mention `-P`, `-s` or `-z`. It *does* document
`--ssl_verify_peer` on 7.x.

| Flag | Argument | Default | Validated range | Both lines? |
|---|---|---|---|---|
| `-d <dir>` | directory to serve | `.` | `/` refused: `Security Error:  You cannot specify the root directory (/) as the source files directory.` | yes |
| `-p <port>` | listen port | 8080 | 1–65535 | yes |
| `-P <port>` | last port of a range | = `-p` | | yes |
| `-l <file>` | log file | none (stderr) | `/` refused | yes |
| `-t <sec>` | connection timeout | 5 | 2–7200, or 0 for none. `Error: -t timeout must be between 2 and 7200, or 0 for no timeout` | yes |
| `-w <sec>` | delay before closing a written target file (e.g. a named pipe) | 0 | 1–7200, or 0. `Error: -w timeout must be between 1 and 7200, or 0 for no timeout` | yes |
| `-k <sec>` | session cleanup timeout | 300 | 300–86400 | yes |
| `-m <bytes>` | max data row length | 32768 | 32KB–**256MB** in a `GPFXDIST` build (libyaml, non-Windows): `Error: -m max row length must be between 32KB and 256MB`. Otherwise 32KB–**1MB**: `… between 32KB and 1MB` | yes |
| `-z <n>` | listen-queue size (internal) | 256 | 16–512 | yes |
| `-S` | open written files `O_SYNC` | off | | yes |
| `-s` | simplified log, no request header | off | | yes |
| `-v` / `-V` | verbose / very verbose | off | | yes |
| `--ssl <dir>` | enable HTTPS; dir holds `server.crt`, `server.key`, `root.crt` | off | `/` refused | yes |
| `--ssl_verify_peer <on/off>` | require client certs | `on` | | **7.x only** |
| `--compress` | zstd transmission | off | requires a zstd build | yes |
| `--multi_thread <n>` | zstd threads; implies `--compress` | off | capped at 256, warns above | yes |
| `-c <file>` | transformation config YAML | none | needs a `GPFXDIST` build | yes |
| `-I <name>` / `-O <name>` | default input / output transformation | none | needs a `GPFXDIST` build | yes |
| `-?`, `--help`, `--version` | | | | yes |
| `-q`, `-h`, `-x` | **removed** | | `The -q, -h and -x options are gone.` then `exit(1)` | yes |

Build notes: `configure` enables gpfdist by default (`--disable-gpfdist` to skip). On
**7.x** `libyaml` is mandatory — `configure` aborts with
`libyaml is required for transformations for gpfdist.`. On **6.x** it is optional; a
missing libyaml only warns and disables transformations, so a 6.x `gpfdist` may not
support `-c`/`-I`/`-O` at all — and its `-m` ceiling drops to 1MB with `GPFXDIST` off.

Compression is by file extension and is handled by libraries linked into gpfdist, not by
`gunzip`/`bunzip2` on `PATH` (`src/backend/utils/misc/fstream/gfile.c`): `.gz` needs
`HAVE_LIBZ` (`.gz not supported` otherwise), `.bz2` needs `HAVE_LIBBZ2`
(`.bz2 not supported`), `.zst` needs a zstd build. `.gz` and `.zst` work for **writable**
external tables too; only `.bz2` is read-only
(`.bz2 not yet supported for writable tables`). `.z` and `.zip` are refused, and any
refusal comes back to the segment as HTTP `415 Unsupported File Type`. All of this is
separate from `--compress`, which zstd-compresses the HTTP stream itself.

### Transformations

`LOCATION('gpfdist://host:8080/data.xml#transform=dblp_input')` plus a `-c config.yaml`
of the shape in `gpMgmt/demo/gpfdist_transform/config.yaml`:

```yaml
---
VERSION: 1.0.0.1
TRANSFORMATIONS:
  dblp_input:
    TYPE:     input
    COMMAND:  /bin/bash dblp/input_transform.sh %filename%
  dblp_output:
    TYPE:     output
    COMMAND:  /bin/bash dblp/output_transform.sh %filename%
```

The `#transform=` fragment is stripped from the URL and sent as the `X-GP-TRANSFORM`
HTTP header (`url_curl.c`).

## gpload control file reference

`gpMgmt/bin/gpload.py` `valid_tokens` is the authority and is **byte-identical on 6.x and
7.x**. Keys are case-insensitive; the doc uses upper case. `parent` is the block a key
must appear in.

| Key | Parent | Required | Notes |
|---|---|---|---|
| `VERSION` | — | no | `1.0.0.1` |
| `DATABASE`, `USER`, `HOST`, `PORT`, `PASSWORD` | — | no | Fall back to `$PGDATABASE`/`$PGUSER`/`$PGHOST`/`$PGPORT`. `PASSWORD` works but is absent from `gpload_help`'s control-file schema — the help only covers the `-W` flag and `$PGPASSWORD` |
| `GPLOAD` | — | **yes** | Wraps `INPUT` + `OUTPUT` |
| `INPUT` | `GPLOAD` | **yes** | |
| `SOURCE` | `INPUT` | **yes** | Repeatable; one gpfdist instance per block |
| `LOCAL_HOSTNAME` | `SOURCE` | no | List; one entry per NIC to use them all |
| `PORT` | `SOURCE` | no | Beats `PORT_RANGE` |
| `PORT_RANGE` | `SOURCE` | no | `[start, end]`; default pool is 8000–9000 |
| `FILE` | `SOURCE` | **yes** | Files, named pipes, directories, globs; `.gz`/`.bz2` auto-decompressed |
| `SSL` | `SOURCE` | no | true starts gpfdist with `--ssl` and uses `gpfdists://` |
| `CERTIFICATES_PATH` | `SOURCE` | when `SSL` | Must hold `server.crt`, `server.key`, `root.crt`; `/` refused |
| `COLUMNS` | `INPUT` | no | `- name: type` list; omit to mirror the target table exactly |
| `TRANSFORM`, `TRANSFORM_CONFIG`, `MAX_LINE_LENGTH` | `INPUT` | no | gpfdist transformations |
| `FORMAT` | `INPUT` | no | `text` (default) or `csv` |
| `DELIMITER`, `ESCAPE`, `NULL_AS`, `QUOTE`, `NEWLINE`, `ENCODING`, `HEADER` | `INPUT` | no | Map onto the FORMAT options above |
| `FORCE_NOT_NULL` | `INPUT` | no | CSV only |
| `FILL_MISSING_FIELDS` | `INPUT` | no | Undocumented in `gpload_help` |
| `ERROR_LIMIT` | `INPUT` | with `LOG_ERRORS` | Emits `segment reject limit <n>`; must be ≥ 2 (`error_limit must be 2 or higher`) |
| `ERROR_PERCENT` | `INPUT` | no | Undocumented in `gpload_help` — and **never read by `gpload.py`**: it is in `valid_tokens` only, so setting it does nothing |
| `LOG_ERRORS` | `INPUT` | no | Default false. Requires `ERROR_LIMIT`, else `gpload:input:log_errors requires gpload:input:error_limit to be specified` |
| `ERROR_TABLE` | `INPUT` | no | **Dead, but silently accepted**: warns `ERROR_TABLE is not supported. We will set LOG_ERRORS and REUSE_TABLES to True for compatibility.` and forces both on |
| `FULLY_QUALIFIED_DOMAIN_NAME` | `INPUT` | no | Undocumented in `gpload_help` |
| `EXTERNAL` | `GPLOAD` | no | Wraps `SCHEMA` |
| `SCHEMA` | `EXTERNAL` | no | Schema for the generated external table; `'%'` means "same as `TABLE`" |
| `OUTPUT` | `GPLOAD` | **yes** | |
| `TABLE` | `OUTPUT` | **yes** | `schema.table` |
| `MODE` | `OUTPUT` | no | `insert` (default), `update`, `merge` |
| `MATCH_COLUMNS` | `OUTPUT` | with update/merge | Join keys |
| `UPDATE_COLUMNS` | `OUTPUT` | with update/merge | Columns to set |
| `UPDATE_CONDITION` | `OUTPUT` | no | WHERE fragment; bare column names are rewritten to `into_table.<col>` |
| `MAPPING` | `OUTPUT` | no | `target: source` or `target: '<expression>'` |
| `PRELOAD` | `GPLOAD` | no | |
| `TRUNCATE` | `PRELOAD` | no | Empties the target first |
| `REUSE_TABLES` | `PRELOAD` | no | Keep external/staging tables for the next run — the trickle-load knob |
| `FAST_MATCH` | `PRELOAD` | no | Undocumented in `gpload_help` |
| `STAGING_TABLE` | `PRELOAD` | no | Undocumented in `gpload_help` |
| `SQL` | `GPLOAD` | no | Wraps `BEFORE` / `AFTER` |
| `BEFORE` / `AFTER` | `SQL` | no | Lists of SQL strings, run in order |

Command-line flags (`gpload.py` docstring — `--max_retries` is missing from
`gpMgmt/doc/gpload_help` on both lines):

`-f <control_file>` (required), `-h`, `-p`, `-U`, `-d`, `-W`, `-q`, `-D` (validate only),
`-v`, `-V`, `-l <logfile>`, `--no_auto_trans`, `--gpfdist_timeout <sec>`,
`--max_retries <n>` (0 disables, -1 forever), `--version`, `-?`.

Log lines are `<timestamp>|<level>|<message>` with levels `DEBUG|LOG|INFO|WARN|ERROR`
(`elevel2str` in `gpload.py`); an `ERROR` line calls `sys.exit`. The summary lines to grep
for are `INFO|rows Inserted          = N`, `INFO|rows Updated           = N`,
`INFO|data formatting errors = N`, then exactly one of `INFO|gpload succeeded`,
`INFO|gpload succeeded with warnings`, `INFO|gpload failed`. Rejected rows are reported at
**WARN**, not INFO: `WARN|N bad rows` (or `WARN|1 bad row`).

Interpreter: 7.x `gpload` is `#!/usr/bin/env python3` using `psycopg2`; 6.x runs under
python 2.7+ or 3 via `builtins`/`future` shims. Both need `pyyaml`.

## Error-log functions

| Function | 6.x | 7.x |
|---|---|---|
| `gp_read_error_log(exttable text)` | built in, OID 7076 | built in, OID 7076 |
| `gp_truncate_error_log(text) → bool` | built in, OID 7069 | built in, OID 7069 |
| `gp_read_persistent_error_log(exttable text)` | run `$GPHOME/share/postgresql/contrib/gpexterrorhandle.sql` | built in, OID 7080 |
| `gp_truncate_persistent_error_log(text) → bool` | same script | built in, OID 7081 |

Columns returned by both readers: `cmdtime timestamptz, relname text, filename text,
linenum int4, bytenum int4, errmsg text, rawdata text, rawbytes bytea`. Both are
`EXECUTE ON ALL SEGMENTS`.

Truncate arguments: a relation name; `'*'` for every relation in the current database
(database owner); `'*.*'` for every database (superuser, else
`must be superuser to delete all error log files`).

On-disk layout (`src/backend/cdb/cdbsreh.c`), relative to each segment's data directory:

| Kind | Path |
|---|---|
| Normal | `errlog/<dbid>_<relid>` |
| Persistent | `errlogpersistent/<dbid>_<namespace_oid>_<relname>` |

## GUCs that change loading behaviour

All defaults verified in `src/backend/utils/misc/guc_gp.c` on both lines; values are
identical unless noted.

| GUC | Default | Context | Effect |
|---|---|---|---|
| `gp_external_max_segs` | 64 | USERSET | Max segments that connect to a single gpfdist URL |
| `gp_reject_percent_threshold` | 300 | USERSET | PERCENT reject limits are not evaluated until this many rows have been processed |
| `gp_initial_bad_row_limit` | 1000 | USERSET | Abort if the first N rows on a segment are all bad, regardless of REJECT LIMIT |
| `gp_external_enable_exec` | on | **POSTMASTER** | Allows `EXECUTE` external web tables; needs a restart to change |
| `gp_external_enable_filter_pushdown` | on | USERSET | "Enable passing of query constraints to external table providers" |
| `readable_external_table_timeout` | 0 (off) | USERSET | Cancel the **read** if no data arrives for N seconds: `segment has not received data from gpfdist for long time, cancelling the query.` |
| `gpfdist_retry_timeout` | 300 | USERSET | **Write path only** — set as `CURLOPT_TIMEOUT` `if (forwrite)` and bounds the POST retry loop (`url_curl.c`). Has no effect on a read. Range 1–7200 |
| `writable_external_table_bufsize` | 1024 kB | USERSET | Buffer before POSTing to gpfdist; range 32–131072 kB |
| `gp_enable_segment_copy_checking` | on | USERSET, hidden (`GUC_NO_SHOW_ALL \| GUC_NOT_IN_SAMPLE`) | Verify the distribution key on `COPY FROM … ON SEGMENT` |
| `gp_ignore_error_table` | off | USERSET, hidden (`GUC_NO_SHOW_ALL \| GUC_NOT_IN_SAMPLE`) | Downgrade `LOG ERRORS INTO <table>` from ERROR to WARNING |
| `gp_autostats_mode` | `none` | USERSET | `none`, `on_change`, `on_no_stats`; 6.x adds `on_change_and_no_stats` and ships `gp_autostats_mode=on_no_stats` in `postgresql.conf.sample`, 7.x ships nothing |
| `gp_autostats_on_change_threshold` | 2147483647 | USERSET | Row count that arms `on_change` |
| `gp_appendonly_compaction_threshold` | 10 (percent) | USERSET | Below this dead-row ratio, `VACUUM` skips an AO segment file |

## 6.x / 7.x delta summary

| Area | 6.x | 7.x |
|---|---|---|
| External table representation | Real relation, `pg_class.relstorage = 'x'` (`RELSTORAGE_EXTERNAL`); `pg_exttable` is a catalog table | Foreign table, `relkind = 'f'`, server `gp_exttable_server`, `pg_exttable` is a view over a function from the `gp_exttable_fdw` extension (installed by `initdb`) |
| `\d ext_table` | `External table "public.x"` | `Foreign table "public.x"` plus `FDW options:` |
| `ON COORDINATOR` | not a keyword | accepted (alias of `ON MASTER`) |
| Persistent error-log functions | script `gpexterrorhandle.sql` from `gpcontrib/gp_error_handling` | built into `pg_proc.dat` |
| `mpp_execute 'coordinator'` | rejected | accepted |
| FDW default exec location | `FTEXECLOCATION_MASTER` | `FTEXECLOCATION_COORDINATOR` |
| `gpfdist --ssl_verify_peer` | absent | present, default `on` |
| gpfdist + libyaml | optional (warning) | required (configure error) |
| `gp_autostats_mode` shipped value | `on_no_stats` via `postgresql.conf.sample` | unset, so the built-in `none` applies |
| `gp_autostats_mode` values | + `on_change_and_no_stats`, + `gp_autostats_on_change_ratio_threshold` | three values only |
| `gpload` interpreter | python 2.7+/3 shims, `pygresql`-era | python3, `psycopg2` |
| External access code | `src/backend/access/external/fileam.c` | `src/backend/access/external/external.c` + `gpcontrib/gp_exttable_fdw/extaccess.c` |

## Documentation

| Page | URL |
|---|---|
| External tables overview | https://greengagedb.org/en/docs-gg/current/external_tables_overview.html |
| CREATE EXTERNAL TABLE | https://greengagedb.org/en/docs-gg/current/reference/sql_commands/create_external_table.html |
| CREATE PROTOCOL | https://greengagedb.org/en/docs-gg/current/reference/sql_commands/create_protocol.html |
| COPY | https://greengagedb.org/en/docs-gg/current/reference/sql_commands/copy.html |
| Use gpfdist | https://greengagedb.org/en/docs-gg/current/use_gpfdist.html |
| Use gpload | https://greengagedb.org/en/docs-gg/current/use_gpload.html |
| gpfdist reference | https://greengagedb.org/en/docs-gg/current/reference/utils/gpfdist.html |
| gpload reference | https://greengagedb.org/en/docs-gg/current/reference/utils/gpload.html |
| analyzedb reference | https://greengagedb.org/en/docs-gg/current/reference/utils/analyzedb.html |
| Foreign tables and FDWs | https://greengagedb.org/en/docs-gg/current/foreign_tables.html |
| Collect statistics via ANALYZE | https://greengagedb.org/en/docs-gg/current/statistics_analyze.html |
| VACUUM, including AO tables | https://greengagedb.org/en/docs-gg/current/vacuum.html |
| GUC reference (single page) | https://greengagedb.org/en/docs-gg/current/reference/guc_reference.html |
| `gp_toolkit.gp_skew_coefficients` | https://greengagedb.org/en/docs-gg/current/reference/gp_toolkit/gp_skew_coefficients.html |
| PXF (separate product) | https://greengagedb.org/en/docs-pxf/current/intro.html |

`current` is the Greengage 6 documentation tree; the `/7/` tree has only 42 pages and no
external-table or loading pages, so the 7.x deltas above are not on the site.
