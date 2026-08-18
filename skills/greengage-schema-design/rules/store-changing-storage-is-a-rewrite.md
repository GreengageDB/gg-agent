---
title: Treat storage type as permanent — changing it rewrites every segment
impact: HIGH
impactDescription: "On 6.x there is no ALTER that changes storage at all; on 7.x SET ACCESS METHOD works but rewrites the whole table under an exclusive lock"
tags: [schema, storage, alter-table, migration, access-method]
---

## Treat storage type as permanent — changing it rewrites every segment

**Impact: HIGH**

**On 6.x you cannot change it.** Both spellings are refused in
`src/backend/commands/tablecmds.c`:

| Statement | 6.x result |
|---|---|
| `ALTER TABLE t SET (appendonly=true, orientation=column)` | `ERROR: cannot SET reloption "appendonly"` — the same for `blocksize`, `compresstype`, `compresslevel`, `checksum`, `orientation` |
| `ALTER TABLE t SET WITH (appendonly=true)` | `ERROR: option "appendonly" not supported` — 6.x `SET WITH` accepts only `REORGANIZE` |
| `ALTER TABLE t SET (fillfactor=70)` on a table that is already AO | `ERROR: altering reloptions for append only tables is not permitted` |

The only migration path is create-new, `INSERT INTO ... SELECT`, swap names, drop old —
which means twice the disk and a full reload.

**On 7.x you can, but it is still a full rewrite.** Storage became a table access method,
so `ALTER TABLE ... SET ACCESS METHOD heap | ao_row | ao_column` exists. It builds a
transient relation, copies every row, swaps relfilenodes and rebuilds the indexes
(`src/backend/commands/tablecmds.c`, and the whole flow is exercised by
`src/test/regress/sql/alter_table_set_am.sql`). Behaviours to know:

| Behaviour | Detail |
|---|---|
| Same method is a no-op | `ALTER TABLE t SET ACCESS METHOD ao_row` on a table that already is `ao_row` does not change relfilenodes and keeps existing reloptions |
| Old reloptions are dropped | converting heap → AO discards heap-only options such as `fillfactor`, and the new table inherits `gp_default_storage_options` |
| Equivalent spelling | `ALTER TABLE t SET WITH (appendoptimized=true)` does the same thing; `ALTER TABLE t SET WITH (appendoptimized=false)` converts back to heap |
| Conflicting spellings | `ERROR: ACCESS METHOD is specified as "ao_row" but the WITH option indicates it to be "ao_column"` |

Either way the cost is proportional to the table, so the decision belongs at design time.

**Incorrect (assuming a table can be "switched to AO later"):**

```sql
-- Bad on 6.x: this is simply not allowed
ALTER TABLE sales_fact SET (appendonly=true, orientation=column);
-- ERROR:  cannot SET reloption "appendonly"

ALTER TABLE sales_fact SET WITH (appendonly=true);
-- ERROR:  option "appendonly" not supported
```

**Correct (6.x: recreate and migrate explicitly):**

```sql
-- Good on 6.x: build the target table with the storage you want, then move the data
CREATE TABLE sales_fact_new (LIKE sales_fact INCLUDING DEFAULTS INCLUDING CONSTRAINTS)
WITH (appendoptimized=true, orientation=column, compresstype=zstd, compresslevel=5)
DISTRIBUTED BY (sale_id);

INSERT INTO sales_fact_new SELECT * FROM sales_fact;
ANALYZE sales_fact_new;

BEGIN;
ALTER TABLE sales_fact     RENAME TO sales_fact_old;
ALTER TABLE sales_fact_new RENAME TO sales_fact;
COMMIT;

DROP TABLE sales_fact_old;
```

**Correct (7.x: one statement, still a full rewrite — plan the lock window):**

```sql
-- Good on 7.x
SET gp_default_storage_options = 'compresstype=zstd, compresslevel=5, blocksize=32768';
ALTER TABLE sales_fact SET ACCESS METHOD ao_column;
ANALYZE sales_fact;
```

Note that `LIKE` copies constraints and defaults but **not** the distribution policy in a
way you should rely on — when `LIKE` is the only hint, the distribution is inherited with
the NOTICE `table doesn't have 'DISTRIBUTED BY' clause, defaulting to distribution columns
from LIKE table`. State `DISTRIBUTED BY` explicitly, as above.

Reference: [Table storage types in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/7/table_types.html)
