# Greengage documentation URL map

Lookup material. Every URL below was checked to return HTTP 200 on 2026-08-18. A 404 in a
skill is worse than no link — re-check before adding a new one:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -L https://greengagedb.org/<path>
```

The site returns a real `404` for missing pages (verified against a deliberately bogus
path), so this check is meaningful.

## URL shape

```
greengagedb.org/{en|ru}/docs-gg/{current|7|6.30.1}/<page>.html
```

- `en` and `ru` both exist; cite `en`.
- **`current` is the Greengage 6 tree** (`6.31.0`). 459 pages in the sitemap — the complete manual.
- **`/7/` has exactly 42 pages** — full list below. Everything else 404s there.
- Pinned-version trees exist for released 6 versions (e.g. `6.30.1`). Do not cite them;
  they go stale.

### The trap this creates

`current` documents Greengage **6**, so it documents 6 spellings. Concretely:

| | Result |
|---|---|
| `…/current/reference/utils/gpscp.html` | 200 — the 6.x utility |
| `…/current/reference/utils/gpsync.html` | **404** — the 7.x rename is not in the 6 tree |
| `…/current/reference/guc_reference.html` | 200 — but documents `gp_session_role` as a real GUC, which it is only on 6.x; on 7.x it is an obsolete alias for `gp_role` |
| `…/7/reference/guc_reference.html` | **404** |

**Rule: link `/current/` for concepts and note the 7.x delta in prose.** Link `/7/` only
for a page in the 42-page list. Never silently present a `/current/` page as 7.x behaviour
when a delta exists — check
[reference/version-deltas.md](version-deltas.md) first.

## Reference sub-trees (all under `/current/`)

| Sub-tree | Pattern | Example |
|---|---|---|
| GUCs | `reference/guc_reference.html` (one page, all GUCs) | [guc_reference](https://greengagedb.org/en/docs-gg/current/reference/guc_reference.html) |
| SQL commands | `reference/sql_commands/<lower_snake_case>.html` | [create_table](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/create_table.html), [alter_table](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/alter_table.html), [explain](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/explain.html), [analyze](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/analyze.html), [create_external_table](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/create_external_table.html), [create_resource_group](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/create_resource_group.html) |
| Utilities | `reference/utils/<name>.html` — **`utils`, not `utilities`** | [gpstate](https://greengagedb.org/en/docs-gg/current/reference/utils/gpstate.html), [gpstart](https://greengagedb.org/en/docs-gg/current/reference/utils/gpstart.html), [gpstop](https://greengagedb.org/en/docs-gg/current/reference/utils/gpstop.html), [gpconfig](https://greengagedb.org/en/docs-gg/current/reference/utils/gpconfig.html), [gprecoverseg](https://greengagedb.org/en/docs-gg/current/reference/utils/gprecoverseg.html), [gpexpand](https://greengagedb.org/en/docs-gg/current/reference/utils/gpexpand.html), [gpcheckcat](https://greengagedb.org/en/docs-gg/current/reference/utils/gpcheckcat.html), [gpinitsystem](https://greengagedb.org/en/docs-gg/current/reference/utils/gpinitsystem.html), [gpaddmirrors](https://greengagedb.org/en/docs-gg/current/reference/utils/gpaddmirrors.html), [gpactivatestandby](https://greengagedb.org/en/docs-gg/current/reference/utils/gpactivatestandby.html), [gpfdist](https://greengagedb.org/en/docs-gg/current/reference/utils/gpfdist.html), [gpload](https://greengagedb.org/en/docs-gg/current/reference/utils/gpload.html), [analyzedb](https://greengagedb.org/en/docs-gg/current/reference/utils/analyzedb.html) |
| System catalogs | `reference/pg_catalog/<name>.html` | [gp_segment_configuration](https://greengagedb.org/en/docs-gg/current/reference/pg_catalog/gp_segment_configuration.html), [gp_distribution_policy](https://greengagedb.org/en/docs-gg/current/reference/pg_catalog/gp_distribution_policy.html) |
| gp_toolkit views | `reference/gp_toolkit/<view>.html` | [gp_skew_coefficients](https://greengagedb.org/en/docs-gg/current/reference/gp_toolkit/gp_skew_coefficients.html), [gp_skew_idle_fractions](https://greengagedb.org/en/docs-gg/current/reference/gp_toolkit/gp_skew_idle_fractions.html), [gp_bloat_diag](https://greengagedb.org/en/docs-gg/current/reference/gp_toolkit/gp_bloat_diag.html) |

## Topic pages worth deep-linking (`/current/`)

| Topic | URL |
|---|---|
| Product intro | [intro.html](https://greengagedb.org/en/docs-gg/current/intro.html) |
| Cluster architecture | [architecture.html](https://greengagedb.org/en/docs-gg/current/architecture.html) |
| Distribution policy, skew | [table_distribution.html](https://greengagedb.org/en/docs-gg/current/table_distribution.html) |
| Heap vs AO row vs AO column; *"Table storage and orientation can be declared only at creation"* | [table_types.html](https://greengagedb.org/en/docs-gg/current/table_types.html) |
| Table basics | [table_basics.html](https://greengagedb.org/en/docs-gg/current/table_basics.html) |
| Compression | [table_compression.html](https://greengagedb.org/en/docs-gg/current/table_compression.html) |
| Partitioning (Greenplum-style) | [table_partitioning.html](https://greengagedb.org/en/docs-gg/current/table_partitioning.html) |
| Indexes | [indexes.html](https://greengagedb.org/en/docs-gg/current/indexes.html) |
| Tablespaces | [tablespaces.html](https://greengagedb.org/en/docs-gg/current/tablespaces.html) |
| EXPLAIN, Motion nodes, slices | [analyze_queries.html](https://greengagedb.org/en/docs-gg/current/analyze_queries.html) |
| ANALYZE and statistics | [statistics_analyze.html](https://greengagedb.org/en/docs-gg/current/statistics_analyze.html) |
| Spill files | [spill_files.html](https://greengagedb.org/en/docs-gg/current/spill_files.html) |
| VACUUM | [vacuum.html](https://greengagedb.org/en/docs-gg/current/vacuum.html) |
| gp_toolkit overview | [gp_toolkit.html](https://greengagedb.org/en/docs-gg/current/gp_toolkit.html) |
| Resource groups | [resource_groups.html](https://greengagedb.org/en/docs-gg/current/resource_groups.html) |
| Resource queues | [resource_queues.html](https://greengagedb.org/en/docs-gg/current/resource_queues.html) |
| External tables | [external_tables_overview.html](https://greengagedb.org/en/docs-gg/current/external_tables_overview.html) |
| gpfdist loading | [use_gpfdist.html](https://greengagedb.org/en/docs-gg/current/use_gpfdist.html) |
| gpload loading | [use_gpload.html](https://greengagedb.org/en/docs-gg/current/use_gpload.html) |
| Backup and restore overview | [backup_restore.html](https://greengagedb.org/en/docs-gg/current/backup_restore.html) |
| Initialize a cluster | [initialize_dbms.html](https://greengagedb.org/en/docs-gg/current/initialize_dbms.html) |
| Start / stop | [start_stop_cluster.html](https://greengagedb.org/en/docs-gg/current/start_stop_cluster.html) |
| Check and recover segments | [check_recover_segments.html](https://greengagedb.org/en/docs-gg/current/check_recover_segments.html) |
| Expand the cluster | [expand_cluster.html](https://greengagedb.org/en/docs-gg/current/expand_cluster.html) |
| Demo cluster | [set_up_demo_cluster.html](https://greengagedb.org/en/docs-gg/current/set_up_demo_cluster.html) |
| Build from sources | [build_from_sources.html](https://greengagedb.org/en/docs-gg/current/build_from_sources.html) |
| Docker | [use_docker.html](https://greengagedb.org/en/docs-gg/current/use_docker.html) |
| Interconnect proxy | [interconnect_proxy.html](https://greengagedb.org/en/docs-gg/current/interconnect_proxy.html) |
| Logging | [logging.html](https://greengagedb.org/en/docs-gg/current/logging.html) |
| Roles and privileges | [roles_and_privileges.html](https://greengagedb.org/en/docs-gg/current/roles_and_privileges.html) |
| `pg_hba.conf` | [pg_hba.html](https://greengagedb.org/en/docs-gg/current/pg_hba.html) |
| Connect with psql | [connect_with_psql.html](https://greengagedb.org/en/docs-gg/current/connect_with_psql.html) |
| Migrating from Greenplum 6 | [migrate_from_gp.html](https://greengagedb.org/en/docs-gg/current/migrate_from_gp.html) |

## The complete `/7/` tree — all 42 pages

Anything not on this list does not exist under `/7/`. Prefix each slug below with
**greengagedb.org/en/docs-gg/7/** (see
[table_distribution.html](https://greengagedb.org/en/docs-gg/7/table_distribution.html) for
the shape).

**Concepts and schema (7-specific behaviour lives here):**
`intro.html`, `databases.html`, `schemas.html`, `tablespaces.html`, `table_basics.html`,
`table_types.html`, `table_distribution.html`, `table_compression.html`,
`table_partitioning.html`, **`table_partitioning_declarative.html`** (7-only feature —
PostgreSQL declarative partitioning), `connect_with_psql.html`

**Install, configure, operate:**
`software_requirements.html`, `network_requirements.html`, `pre_configuration.html`,
`initialize_dbms.html`, `initialize_localization.html`, `start_stop_cluster.html`,
`build_from_sources.html`, `set_up_demo_cluster.html`, `use_docker.html`,
`interconnect_proxy.html`, `logging.html`, `backup_restore.html`

**Security and authentication:**
`roles_and_privileges.html`, `access_by_time.html`, `pg_hba.html`, `pg_ident.html`,
`auth_password.html`, `auth_cert.html`, `auth_ident.html`, `encrypt_connections.html`,
`mit_kerberos.html`, `freeipa_kerberos.html`, `freeipa_ldap.html`, `freeipa_ldap_pam.html`

**`ggrebalance` (7-only utility, no 6.x equivalent):**
`rebalance.html`, `reference/utils/ggrebalance.html`,
`reference/ggrebalance/rebalance_status.html`,
`reference/ggrebalance/rebalance_progress.html`,
`reference/ggrebalance/saved_plan.html`,
`reference/ggrebalance/segment_move_steps.html`,
`reference/ggrebalance/table_rebalance_status_detail.html`

There is **no** `/7/` page for GUCs, SQL commands, catalogs, `gp_toolkit` views, any `gp*`
utility other than `ggrebalance`, EXPLAIN, ANALYZE, resource management, or loading.

## gpbackup / gprestore are a separate product tree

Not under `docs-gg` at all:

```
greengagedb.org/en/docs-backup/current/<page>.html
```

| Topic | URL |
|---|---|
| Overview | [overview.html](https://greengagedb.org/en/docs-backup/current/overview.html) |
| Install | [install.html](https://greengagedb.org/en/docs-backup/current/install.html) |
| Full backup and restore | [full_backup_restore.html](https://greengagedb.org/en/docs-backup/current/full_backup_restore.html) |
| Partial backups | [partial_backups.html](https://greengagedb.org/en/docs-backup/current/partial_backups.html) |
| Incremental backups | [incremental_backups.html](https://greengagedb.org/en/docs-backup/current/incremental_backups.html) |
| S3 storage plugin | [plugin-s3.html](https://greengagedb.org/en/docs-backup/current/plugin-s3.html) |
| `gpbackup` syntax | [gpbackup_syntax.html](https://greengagedb.org/en/docs-backup/current/gpbackup_syntax.html) |
| `gprestore` syntax | [gprestore_syntax.html](https://greengagedb.org/en/docs-backup/current/gprestore_syntax.html) |

## Finding a page you do not have a URL for

The sitemap chain is the only reliable index:

```
https://greengagedb.org/sitemap.xml
  -> https://greengagedb.org/en/sitemap-en.xml
       -> https://greengagedb.org/en/sitemap-docs-gg.xml     (docs-gg, all versions)
```

Do not guess a slug. Docs slugs are lower_snake_case and frequently do not match the
obvious noun — `analyze_queries.html` is the EXPLAIN page, `statistics_analyze.html` is the
`ANALYZE` page, and there is no `query_performance.html`, `monitor_cluster.html` or
`distribution_keys.html` (all verified 404).

## What is not in the docs site

The repository's `doc/` directory holds only man-page reference sources — the user manual
is on greengagedb.org and nowhere in the tree. Build, test, CI and contribution procedure
live in `README.md`, `CONTRIBUTING.md`, `ci/readme.md` and `.github/workflows/README.md`
inside the repository, not on the docs site.
