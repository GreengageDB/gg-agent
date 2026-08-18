---
title: Set storage defaults once per session or database, not by copying WITH clauses
impact: MEDIUM
impactDescription: "Repeating the storage clause on hundreds of CREATE TABLE statements guarantees drift; one table ends up uncompressed and nobody notices until it is a terabyte"
tags: [schema, storage, guc, maintainability, defaults]
---

## Set storage defaults once per session or database, not by copying WITH clauses

**Impact: MEDIUM**

Copy-pasting `WITH (appendoptimized=true, orientation=column, compresstype=zstd,
compresslevel=5)` onto every `CREATE TABLE` in a schema is how one table ends up with
`compresslevel=1`, or heap, or a stale `compresstype=quicklz` that a 7.x upgrade then
rejects. Two GUCs exist so you can state the policy once.

| GUC | 6.x accepts | 7.x accepts | Scope |
|---|---|---|---|
| `gp_default_storage_options` | `appendonly`, `orientation`, `blocksize`, `compresstype`, `compresslevel`, `checksum` | `blocksize`, `compresstype`, `compresslevel`, `checksum` **only** | `PGC_USERSET`; also settable per database or per role |
| `default_table_access_method` | — (7.x only) | `heap`, `ao_row`, `ao_column` | `PGC_USERSET` |

Both are `PGC_USERSET`, which is exactly why they must be set somewhere durable —
`ALTER DATABASE`, `ALTER ROLE`, or the top of the migration script — and not left to
whatever the interactive session happens to hold.

The 6.x → 7.x split is the trap: on 7.x, putting `appendonly` or `orientation` into
`gp_default_storage_options` fails with
`ERROR: invalid storage option "appendonly"`,
`HINT: For table access methods use "default_table_access_method" instead.` The storage
*type* and the storage *parameters* are now two different settings.

**Incorrect (policy duplicated on every statement, and drifting):**

```sql
-- Bad: 200 statements like this, one of which quietly says compresslevel=1
CREATE TABLE f_sales (...)  WITH (appendoptimized=true, orientation=column,
                                  compresstype=zstd, compresslevel=5) DISTRIBUTED BY (id);
CREATE TABLE f_returns (...) WITH (appendoptimized=true, orientation=column,
                                  compresstype=zstd, compresslevel=1) DISTRIBUTED BY (id);
```

**Correct (state the policy once, then write plain DDL):**

```sql
-- Good on 7.x: type and parameters set separately, at database scope
ALTER DATABASE analytics SET default_table_access_method = 'ao_column';
ALTER DATABASE analytics SET gp_default_storage_options =
      'blocksize=32768, compresstype=zstd, compresslevel=5, checksum=true';

-- New sessions then get compressed AOCO tables from bare DDL
CREATE TABLE f_sales   (sale_id bigint NOT NULL, amount numeric(12,2))
  DISTRIBUTED BY (sale_id);
CREATE TABLE f_returns (return_id bigint NOT NULL, amount numeric(12,2))
  DISTRIBUTED BY (return_id);

-- and a table that genuinely needs to be heap opts out explicitly
CREATE TABLE control_table (job text PRIMARY KEY, state text)
  USING heap DISTRIBUTED REPLICATED;
```

```sql
-- Good on 6.x: one GUC carries both the type and the parameters
ALTER DATABASE analytics SET gp_default_storage_options =
      'appendonly=true, orientation=column, blocksize=32768, compresstype=zstd, compresslevel=5';
```

Verify what a session will actually produce before running a migration:

```sql
SHOW gp_default_storage_options;
SHOW default_table_access_method;   -- 7.x only
```

Reference: [Server configuration parameters (GUCs) overview](https://greengagedb.org/en/docs-gg/current/reference/guc_reference.html)
