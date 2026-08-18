---
title: Choose heap, append-optimized row or append-optimized column by workload, not by habit
impact: CRITICAL
impactDescription: "A wide fact table scanned for three columns reads every byte of every row as heap or AO row; as AO column it reads only the three columns' files"
tags: [schema, storage, append-optimized, orientation]
---

## Choose heap, append-optimized row or append-optimized column by workload, not by habit

**Impact: CRITICAL**

`heap` is the PostgreSQL default and the wrong default for an analytical table. It is
row-oriented, uncompressed, and carries per-row MVCC overhead sized for concurrent
single-row updates. Append-optimized storage drops most of that bookkeeping and adds
compression; column orientation additionally stores each column in its own segment file,
so a query that names three of forty columns reads three files instead of forty.

| Storage | Written as (7.x) | Written as (6.x) | Fits |
|---|---|---|---|
| Heap | `USING heap` (the default) | default | Small tables; frequent single-row `INSERT`/`UPDATE`/`DELETE`; anything needing `CLUSTER` |
| AO row | `USING ao_row` | `WITH (appendonly=true, orientation=row)` | Bulk-loaded tables where most queries touch most columns; wide `SELECT *` |
| AO column | `USING ao_column` | `WITH (appendonly=true, orientation=column)` | Wide fact tables where queries touch few columns; aggregates over one or two columns; the best compression |

On 7.x these are PostgreSQL table access methods, registered in
`src/include/catalog/pg_am.dat` as `heap`, `ao_row` and `ao_column`. The legacy
`WITH (appendoptimized=..., orientation=...)` spelling still parses on 7.x and is
translated to the matching access method by `greengageLegacyAOoptions()` in
`src/backend/parser/gram.y` — `USING` wins if both are given.

Column orientation is not free: every column adds a file per segment, so a 400-column
table on 24 segments is ~9600 files before partitioning multiplies it. For narrow tables,
or when queries genuinely read whole rows, AO row wins.

**Incorrect (heap for a wide bulk-loaded fact table):**

```sql
-- Bad: 40 columns, loaded nightly, queried three columns at a time,
--      but stored uncompressed row-wise with full heap MVCC overhead
CREATE TABLE sales_fact (
    sale_id     bigint NOT NULL,
    sale_date   date   NOT NULL,
    store_id    int,
    product_id  int,
    amount      numeric(12,2)
    -- ... 35 more columns
)
DISTRIBUTED BY (sale_id);
```

**Correct (append-optimized, column-oriented, compressed):**

```sql
-- Good (7.x): access method spells the intent; only the columns named are read
CREATE TABLE sales_fact (
    sale_id     bigint NOT NULL,
    sale_date   date   NOT NULL,
    store_id    int,
    product_id  int,
    amount      numeric(12,2)
)
USING ao_column
WITH (compresstype=zstd, compresslevel=5)
DISTRIBUTED BY (sale_id);

-- Same table on 6.x (and still accepted on 7.x):
CREATE TABLE sales_fact_6x (
    sale_id     bigint NOT NULL,
    sale_date   date   NOT NULL,
    store_id    int,
    product_id  int,
    amount      numeric(12,2)
)
WITH (appendoptimized=true, orientation=column, compresstype=zstd, compresslevel=5)
DISTRIBUTED BY (sale_id);
```

Check what a table actually is — on 7.x read `pg_am`, on 6.x read `pg_appendonly`:

```sql
-- 7.x
SELECT c.relname, am.amname, c.reloptions
FROM   pg_class c LEFT JOIN pg_am am ON am.oid = c.relam
WHERE  c.relname = 'sales_fact';

-- 6.x
SELECT relid::regclass, columnstore, compresstype, compresslevel, blocksize
FROM   pg_appendonly WHERE relid = 'sales_fact'::regclass;
```

Reference: [Table storage types in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/7/table_types.html)
