---
title: Always write an explicit DISTRIBUTED clause on every CREATE TABLE
impact: CRITICAL
impactDescription: "Omitting it makes the key depend on constraint order, inheritance, LIKE and a GUC; the silently chosen key is often the worst column in the table"
tags: [schema, distribution, ddl]
---

## Always write an explicit DISTRIBUTED clause on every CREATE TABLE

**Impact: CRITICAL**

When you omit the clause, `src/backend/parser/parse_utilcmd.c` walks the cascade below to
invent one, and each step depends on something other than your intent:

| Order | Condition | Result | NOTICE emitted |
|---|---|---|---|
| 1 | `INHERITS (parent)` | parent's policy | `table has parent, setting distribution columns to match parent table` |
| 2 | `LIKE other` | other's policy | `table doesn't have 'DISTRIBUTED BY' clause, defaulting to distribution columns from LIKE table` |
| 3 | a `PRIMARY KEY` / `UNIQUE` exists | the columns common to all of them | — |
| 4 | `gp_create_table_random_default_distribution=on` | `DISTRIBUTED RANDOMLY` | `using default RANDOM distribution since no distribution was specified` |
| 5 | otherwise | **the first column with a hash opclass** | `Table doesn't have 'DISTRIBUTED BY' clause -- Using column named '<col>' as the Greengage Database data distribution key for this table.` |
| 6 | no hashable column at all | empty key, rows land arbitrarily | `Table doesn't have 'DISTRIBUTED BY' clause, and no column type is suitable for a distribution key. Creating a NULL policy entry.` |

Step 5 is the common case and it is almost always wrong: the first column of a fact table
is typically a low-cardinality status, a load date, or a surrogate that nothing joins on.
`gp_create_table_random_default_distribution` has boot value `false` in
`src/backend/utils/misc/guc_gp.c` on both 6.x and 7.x, so step 4 normally does not fire —
but it is `PGC_USERSET`, so any session or role can flip it and change what your DDL
script produces.

**Incorrect (no clause — the key is whatever column happens to be first):**

```sql
-- Bad: silently distributes on load_batch_id, which has ~30 distinct values
CREATE TABLE public.sales_fact (
    load_batch_id int,
    sale_id       bigint,
    customer_id   bigint,
    sold_at       timestamptz,
    amount        numeric(12,2)
);
-- NOTICE:  Table doesn't have 'DISTRIBUTED BY' clause -- Using column named
--          'load_batch_id' as the Greengage Database data distribution key for this table.
```

**Correct (the key is a decision, written down):**

```sql
-- Good: sale_id is unique, so rows hash uniformly across all segments
CREATE TABLE public.sales_fact (
    load_batch_id int,
    sale_id       bigint,
    customer_id   bigint,
    sold_at       timestamptz,
    amount        numeric(12,2)
)
DISTRIBUTED BY (sale_id);
```

Audit an existing schema for accidental keys:

```sql
SELECT c.relname,
       p.policytype,
       pg_catalog.pg_get_table_distributedby(c.oid) AS distributed_by
FROM   gp_distribution_policy p
JOIN   pg_class   c ON c.oid = p.localoid
JOIN   pg_namespace n ON n.oid = c.relnamespace
WHERE  n.nspname NOT IN ('pg_catalog','information_schema','gp_toolkit')
ORDER  BY 1;
```

Reference: [Overview of the CREATE TABLE SQL command](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/create_table.html)
