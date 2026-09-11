# Where a documentation claim is settled in the source

Lookup material. Paths were read with `git ls-tree -r refs/remotes/origin/7.x` and
`refs/remotes/origin/6.x` of `GreengageDB/greengage`, and from the GitHub API for
`GreengageDB/gpbackup` and `GreengageDB/pxf`, on 2026-08-31. Re-read the tree at the ref you
are checking against: a path that moved between lines is exactly the kind of fact this table
exists to stop you from guessing.

## Greengage DB

| Claim in the documentation | Settled by | Notes |
|---|---|---|
| A Greengage-specific GUC: name, type, default, range, context | `src/backend/utils/misc/guc_gp.c` | the definition record carries the default and the bounds |
| An inherited PostgreSQL GUC | `src/backend/utils/misc/guc.c` | 7.x is PostgreSQL 12.22, 6.x is 9.4.26 — upstream defaults differ between them |
| The shipped default in a fresh cluster | `src/backend/utils/misc/postgresql.conf.sample` | what `initdb` writes, which is not always the compiled-in default |
| A catalog table or column | `src/include/catalog/*.h` | e.g. `pg_resgroup.h`; the header is the definition, the docs are a copy of it |
| A `gp_toolkit` view or its columns | **7.x** `gpcontrib/gp_toolkit/gp_toolkit--<version>.sql`; **6.x** `src/backend/catalog/gp_toolkit.sql` | the extension moved between the lines — read the right one |
| SQL syntax, a clause, or a synopsis | `doc/src/sgml/ref/<command>.sgml` | the in-tree reference page; `allfiles.sgml` lists them |
| A management utility's flags and behaviour | `gpMgmt/bin/<utility>` | `gpconfig`, `gpstate`, `gprecoverseg`, `gpexpand`, `gpinitsystem`, `ggrebalance` and the rest are scripts you can read |
| The version itself | `VERSION`, `getversion`, `configure.in` | never infer the version from a branch name |

`ggrebalance` and `gpcheckresgroupv2impl` exist on 7.x; check before documenting a utility as
available on both lines.

## gpbackup and gprestore — `GreengageDB/gpbackup`

Default branch `master`. It ships outside the `greengage` repository, so its version and its
flags move independently of the database.

| Claim | Settled by |
|---|---|
| A `gpbackup`/`gprestore` flag: name, default, whether it takes a value | `options/flag.go` |
| Flag validation and mutual exclusions | `options/options.go` |
| Backup behaviour, metadata and the table filter | `backup/` |
| Restore behaviour | `restore/` |
| Storage plugin API and the shipped plugins | `plugins/` |
| The helper process used on segments | `helper/` |

## PXF — `GreengageDB/pxf`

Default branch `main` (not `master` — the two repositories differ).

| Claim | Settled by |
|---|---|
| A `pxf` CLI command or flag | `cli/cmd/*.go` — `pxf.go`, `cluster.go`, `root.go` |
| Server-side profile, connector or configuration property | `server/` |
| Foreign-data-wrapper syntax and options | `fdw/` |
| External-table syntax and options | `external-table/` |
| PXF's own documentation, for comparison | `docs/` |

## Checking against a live cluster

Only where the source cannot settle it — an effective default after `gpconfig`, a view's real
column list, a plan shape. Bring the cluster up with
[greengage-cluster-ops](../../greengage-cluster-ops/SKILL.md); do not reinvent connection
handling.

```sql
SELECT name, setting, boot_val, reset_val, unit, context
  FROM pg_settings WHERE name = '<guc>';        -- boot_val is the compiled-in default
\d+ gp_toolkit.<view>                            -- the real column list
SELECT version();                                -- the ref you are actually testing
```

**A live cluster answers "what does this instance do", not "what does this release do".** A
value read from a cluster somebody configured is evidence about that cluster. When the two
disagree, the source at the pinned ref wins for a documentation claim, and the difference is
worth a sentence in the report.
