---
title: Write the storage clause explicitly and use the spelling your version expects
impact: MEDIUM-HIGH
impactDescription: "Storage silently inherits from gp_default_storage_options or default_table_access_method, so identical DDL produces different tables in different sessions"
tags: [schema, storage, ddl, guc, portability]
---

## Write the storage clause explicitly and use the spelling your version expects

**Impact: MEDIUM-HIGH**

A `CREATE TABLE` with no storage clause does not mean "heap, uncompressed". It means
"whatever `default_table_access_method` and `gp_default_storage_options` happen to say in
this session", and both are `PGC_USERSET`. A DDL script that produced heap tables on your
laptop can produce zstd-compressed AO column tables in production. Write the clause.

The spellings, and what breaks:

| Form | 6.x | 7.x |
|---|---|---|
| `WITH (appendonly=true, orientation=column)` | native reloption | accepted, translated to `USING ao_column` (`greengageLegacyAOoptions`, `src/backend/parser/gram.y`) |
| `WITH (appendoptimized=true, ...)` | accepted alias | accepted, same translation |
| `USING ao_row` / `USING ao_column` / `USING heap` | **not available** | native; **takes precedence over the `WITH` options** |
| `WITH (orientation=column)` alone | `ERROR: invalid option "orientation" for base relation` (`HINT: ... Append Only relations ...`) | `ERROR: invalid option "orientation" for base relation`, `HINT: Table orientation only valid for Append Optimized relations, create an AO relation to use table orientation.` |
| `gp_default_storage_options = 'appendonly=true, orientation=column'` | valid | `ERROR: invalid storage option "appendonly"`, `HINT: For table access methods use "default_table_access_method" instead.` (same for `appendoptimized` and `orientation`) |

That last row is the migration trap: a 6.x `postgresql.conf` or `ALTER DATABASE ... SET`
that puts `appendonly` or `orientation` into `gp_default_storage_options` is rejected
outright on 7.x, by the GUC's check hook, before any table is created. On 7.x,
`gp_default_storage_options` accepts only `blocksize`,
`compresstype`, `compresslevel` and `checksum`; the storage *type* moved to
`default_table_access_method`.

**Incorrect (relies on session defaults; and mixes 7.x-only syntax into a shared script):**

```sql
-- Bad: no storage clause at all — the result depends on the session
CREATE TABLE sales_fact (sale_id bigint, amount numeric(12,2))
DISTRIBUTED BY (sale_id);

-- Bad: orientation without appendoptimized
CREATE TABLE sales_fact2 (sale_id bigint, amount numeric(12,2))
WITH (orientation=column)
DISTRIBUTED BY (sale_id);
-- ERROR:  invalid option "orientation" for base relation
```

**Correct (explicit, and portable across both lines):**

```sql
-- Good: this exact statement produces an AO column table on 6.x and on 7.x
CREATE TABLE sales_fact (
    sale_id bigint NOT NULL,
    amount  numeric(12,2)
)
WITH (appendoptimized=true, orientation=column, compresstype=zstd, compresslevel=5)
DISTRIBUTED BY (sale_id);
```

Prefer the `WITH (appendoptimized=...)` form in scripts that must run on both lines, and
`USING ao_column` in 7.x-only code where the intent reads better. Never write both with
different meanings — on `ALTER TABLE` that is a hard error:
`ACCESS METHOD is specified as "ao_row" but the WITH option indicates it to be "ao_column"`.

Reference: [Table storage types in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/7/table_types.html)
