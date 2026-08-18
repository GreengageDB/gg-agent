# `gpbackup` / `gprestore` flag reference

Taken from
[gpbackup_syntax.html](https://greengagedb.org/en/docs-backup/current/gpbackup_syntax.html)
and
[gprestore_syntax.html](https://greengagedb.org/en/docs-backup/current/gprestore_syntax.html).
These utilities live in `https://github.com/GreengageDB/gpbackup`, **not** in
`GreengageDB/greengage`, and are versioned independently of the server.

## `gpbackup` synopsis

```
gpbackup --dbname <database_name>
  [--backup-dir <directory>]
  [--compression-level <level>]
  [--compression-type <type>]
  [--copy-queue-size <int>]
  [--data-only]
  [--debug]
  [--exclude-schema <schema> [...]]
  [--exclude-table <schema.table> [...]]
  [--exclude-schema-file <file_name>]
  [--exclude-table-file <file_name>]
  [--include-schema <schema> [...]]
  [--include-table <schema.table> [...]]
  [--include-schema-file <file_name>]
  [--include-table-file <file_name>]
  [--incremental [--from-timestamp <backup-timestamp>]]
  [--jobs <int>]
  [--leaf-partition-data]
  [--metadata-only]
  [--no-compression]
  [--no-inherits]
  [--no-history]
  [--plugin-config <config_file_location>]
  [--quiet]
  [--single-data-file]
  [--single-backup-dir]
  [--verbose]
  [--with-stats]
  [--without-globals]
gpbackup --help
gpbackup --version
```

## `gpbackup` options

| Flag | Meaning | Notes |
|---|---|---|
| `--dbname <db>` | Database to back up | Mandatory |
| `--backup-dir <dir>` | Destination directory | Must be an absolute path; `gpadmin` needs write access **on every host** |
| `--compression-level <1-9>` | Compression intensity | Default `1`; incompatible with `--no-compression` |
| `--compression-type <gzip\|zstd>` | Compression algorithm | Default `gzip`; incompatible with `--no-compression` |
| `--no-compression` | Write uncompressed data files | Incompatible with `--compression-type` and `--compression-level` |
| `--copy-queue-size <int>` | Pre-initialised `COPY` commands | Incompatible with `--jobs`; **requires `--single-data-file`** — `--copy-queue-size must be specified with --single-data-file` |
| `--jobs <int>` | Parallel jobs | Default 1; incompatible with `--metadata-only` and `--single-data-file` |
| `--data-only` | Table data only, no DDL | Incompatible with `--metadata-only` and `--incremental` |
| `--metadata-only` | DDL only, no data | Incompatible with `--incremental`, `--jobs`, `--data-only`, `--leaf-partition-data` |
| `--include-schema <s>` | Back up only these schemas | Repeatable; only combinable with `--exclude-table` |
| `--exclude-schema <s>` | Back up everything except these | Repeatable |
| `--include-table <s.t>` | Back up only these relations | Repeatable; **schema-qualified**; also matches sequences, views, materialized views |
| `--exclude-table <s.t>` | Back up everything except these | Repeatable |
| `--include-schema-file`, `--exclude-schema-file`, `--include-table-file`, `--exclude-table-file` | Same, one name per line in a plain text file | |
| `--no-inherits` | Ignore inheritance when resolving included tables | Requires `--include-table` or `--include-table-file` — `--no-inherits must be specified with either --include-table or --include-table-file` |
| `--leaf-partition-data` | One data file per leaf partition | Prerequisite for `--incremental`; enables partition-level include/exclude. Without it "the entire table is saved to one data file per segment" |
| `--incremental` | Append an incremental to a set | `--leaf-partition-data must be specified with --incremental`, on this and every prior backup in the set |
| `--from-timestamp <ts>` | Pin the incremental base | `--from-timestamp must be specified with --incremental`. Without it, the base is chosen from the history database |
| `--single-data-file` | One data file per segment for all tables | Uses `gpbackup_helper` on the segments; the result cannot be restored with `gprestore --jobs` |
| `--single-backup-dir` | One directory per host instead of per segment | `--single-backup-dir must be specified with --backup-dir` |
| `--with-stats` | Include table statistics | Required if you later want `gprestore --with-stats` |
| `--without-globals` | Exclude roles, tablespaces, resource queues/groups | Globals are included by default |
| `--no-history` | Do not record this backup in the history database | Breaks automatic base selection for later `--incremental` runs |
| `--plugin-config <file>` | Storage plugin YAML | Incompatible with `--backup-dir` |
| `--quiet` / `--verbose` / `--debug` | Output verbosity | |

### Object naming rules for the filters

- Table names must be schema-qualified: `sales.orders`.
- Names containing uppercase letters or special characters must be double-quoted exactly
  as stored in the catalog: `--include-table '"SalesData"."Quarterly Totals"'`.
- The table-level options also apply to sequences, views and materialized views.
- Only the **root** table name and **leaf** partition names may be used; "Intermediate
  partitions in multi-level partition hierarchies cannot be specified directly."
- The root table's metadata is always included when any of its partitions is backed up.

## `gprestore` synopsis

```
gprestore --timestamp <YYYYMMDDHHMMSS>
  [--backup-dir <directory>]
  [--copy-queue-size <int>]
  [--create-db]
  [--debug]
  [--exclude-schema <schema> ...] [--exclude-schema-file <file_name>]
  [--exclude-table <schema.table> ...] [--exclude-table-file <file_name>]
  [--include-schema <schema> ...] [--include-schema-file <file_name>]
  [--include-table <schema.table> ...] [--include-table-file <file_name>]
  [--truncate-table]
  [--redirect-schema <schema>]
  [--resize-cluster]
  [--data-only | --metadata-only]
  [--incremental]
  [--jobs <int>]
  [--on-error-continue]
  [--plugin-config <config_file_location>]
  [--quiet]
  [--redirect-db <database_name>]
  [--verbose]
  [--version]
  [--with-globals]
  [--with-stats]
  [--run-analyze]
gprestore --help
```

## `gprestore` options

| Flag | Meaning | Notes |
|---|---|---|
| `--timestamp <YYYYMMDDHHMMSS>` | Which backup to restore | The documented required argument; there is no "latest". Omitting it gives `Must provide --backup-dir if --timestamp is not provided` |
| `--backup-dir <dir>` | Where the backup files are | Must match the `gpbackup --backup-dir` used |
| `--create-db` | Create the target database if absent | From `template0`; incompatible with `--data-only` |
| `--redirect-db <db>` | Restore into a different database name | The workhorse for verification restores |
| `--redirect-schema <schema>` | Restore objects into a different schema | Requires an include filter (`Cannot use --redirect-schema without --include-table, --include-table-file, --include-schema, or --include-schema-file`); rejects every exclude filter |
| `--resize-cluster` | Target has a different segment count | Not usable for incremental sets: "Incremental backups can't be restored after changes in the cluster segment configuration" |
| `--data-only` | Data only | Tables must already exist; incompatible with `--metadata-only`, `--create-db`, `--with-globals` |
| `--metadata-only` | DDL only | Objects must **not** already exist |
| `--truncate-table` | `TRUNCATE` before loading | `Cannot use --truncate-table without --include-table or --include-table-file and without --data-only`; also rejects `--metadata-only`, `--incremental`, `--redirect-schema` |
| `--incremental` | Restore the data of **one** backup out of a set | "Other backups from the same incremental backup set are ignored." `Cannot use --incremental without --data-only`. To restore the whole set, give the newest `--timestamp` and omit this flag |
| `--with-globals` | Restore roles, tablespaces, resource queues and groups | Off by default |
| `--with-stats` | Restore statistics from the backup | Requires `gpbackup --with-stats`; incompatible with `--run-analyze` |
| `--run-analyze` | `ANALYZE` restored tables instead | Use when the backup carried no stats; incompatible with `--with-stats` |
| `--on-error-continue` | Keep going past SQL errors | Read the report file afterwards; a "successful" run can be partial |
| `--jobs <int>` | Parallel restore jobs | Not usable against a `--single-data-file` backup |
| `--copy-queue-size <int>` | Pre-initialised `COPY` commands | Incompatible with `--jobs` |
| `--include-*` / `--exclude-*` | Same filter set as `gpbackup` | |
| `--plugin-config <file>` | Storage plugin YAML | Must be the same plugin the backup used |

## Files a backup leaves behind

| Path | Contents |
|---|---|
| `<coordinator datadir>/backups/<YYYYMMDD>/<ts>/` | `gpbackup_<ts>_metadata.sql` (DDL), `gpbackup_<ts>_toc.yaml`, `gpbackup_<ts>_config.yaml`, `gpbackup_<ts>_report`, and `gpbackup_<ts>_statistics.sql` when `--with-stats` was given |
| `<segment datadir>/backups/<YYYYMMDD>/<ts>/` | that segment's data files, named `gpbackup_<content-id>_<ts>_<OID>.gz` |
| `<coordinator datadir>/gpbackup_history.db` | SQLite history (legacy `gpbackup_history.yaml`) |
| `gpbackup_<ts>_report` | per-backup summary |
| `gprestore_<backup_ts>_<restore_ts>_report` | per-restore summary |
| `~/gpAdminLogs/gpbackup_YYYYMMDD.log`, `gprestore_YYYYMMDD.log` | logs |

With `--backup-dir /path`, the layout becomes `/path/gpseg-1/backups/<YYYYMMDD>/<ts>/` on
the coordinator and `/path/gpseg<N>/backups/<YYYYMMDD>/<ts>/` on the segments.

## Storage plugin contract

Config file (`--plugin-config`), the only required key being `executablepath`, which is
resolved on **every** host:

```yaml
executablepath: $GPHOME/bin/gpbackup_s3_plugin
options:
  region: garage
  endpoint: http://10.92.40.164:3900
  aws_access_key_id: GK8bbdf080f0717c03add3e461
  aws_secret_access_key: 28efc14dfa24b7965e74a69b7a3a619e2b49e090875c883377b5a61ba0b48f05
  bucket: test-backup-bucket
  folder: test/ggbackup
```

Keys the S3 plugin accepts under `options`: `region`, `endpoint`, `aws_access_key_id`,
`aws_secret_access_key`, `aws_session_token`, `bucket`, `folder`, `encryption`,
`backup_max_concurrent_requests`, `backup_multipart_chunksize`,
`restore_max_concurrent_requests`, `restore_multipart_chunksize`, `http_proxy`,
`remove_duplicate_bucket`. The plugin's own `make build && make install` "copies
`gpbackup_s3_plugin` to `$GPHOME/bin` on all cluster hosts".

Commands a plugin executable must implement, all but `plugin_api_version` and `--version`
taking the config path as the first argument:

| Command | Invocation |
|---|---|
| `setup_plugin_for_backup`, `setup_plugin_for_restore`, `cleanup_plugin_for_backup`, `cleanup_plugin_for_restore` | `<plugin> <cmd> <config_path> <local_backup_dir> <scope> <contentID>` |
| `backup_file`, `restore_file` | `<plugin> <cmd> <config_path> <filepath>` |
| `backup_data`, `restore_data` | `<plugin> <cmd> <config_path> <data_filekey>` |
| `delete_backup` | `<plugin> delete_backup <config_path> <timestamp>` |
| `plugin_api_version`, `--version` | `<plugin> <cmd>` |

Setup and cleanup run at three scopes: `coordinator` (once per cluster), `segment_host`
(once per host), `segment` (once per segment process).

Reference: [gpbackup and gprestore](https://greengagedb.org/en/docs-backup/current/overview.html)
