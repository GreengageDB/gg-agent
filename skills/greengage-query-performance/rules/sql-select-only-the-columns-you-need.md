---
title: Never SELECT * from a column-oriented table
impact: HIGH
impactDescription: "An orientation=column table stores one file per column and reads only the projected ones; SELECT * on a 200-column table reads 200 files instead of 3"
tags: [query-performance, sql, storage, append-optimized, projection]
---

## Never `SELECT *` from a column-oriented table

**Impact: HIGH**

An append-optimized table created `WITH (appendoptimized=true, orientation=column)` stores
each column in its own set of segment files. The scan opens only the files for the columns
the query projects — `src/backend/access/aocs/aocsam.c` iterates `proj_atts` /
`num_proj_atts` and opens a datum stream per projected attribute, and nothing else. Naming
three columns out of two hundred reads roughly 1.5% of the table's bytes.

`SELECT *` throws that away. It also throws away the compression win, because each column
file is compressed with the codec chosen for *that* column
(`pg_attribute_encoding`), so decompressing 200 columns costs 200 codecs' worth of CPU on
every segment.

The effect is smaller but still real on `orientation=row` and heap tables, where the width
of the projected tuple determines how much data crosses a Motion. A `Redistribute Motion`
of `SELECT *` moves every byte of every row; a redistribute of three columns moves three
columns.

**Incorrect (`SELECT *` on a wide column-oriented fact table):**

```sql
-- Bad: reads all 200 column files, decompresses all of them, and moves the
-- full row width across the interconnect.
CREATE TABLE fact_sales (
    sale_id bigint, customer_id bigint, product_id bigint, sale_date date,
    amount numeric /*, ... 195 more columns ... */
)
WITH (appendoptimized = true, orientation = column, compresstype = zstd, compresslevel = 1)
DISTRIBUTED BY (sale_id);

SELECT * FROM fact_sales WHERE sale_date = DATE '2024-06-01';
```

**Correct (project only the columns the query consumes):**

```sql
-- Good: three column files opened, three decompressed, three columns moved.
SELECT customer_id, product_id, amount
FROM   fact_sales
WHERE  sale_date = DATE '2024-06-01';
```

The rule extends to the columns you join and group on: every extra column in the target
list of a subquery that sits below a Motion is bytes on the interconnect. Push the
projection as far down as it will go — select the three columns inside the CTE, not
`SELECT *` inside and a narrow list outside.

Check a table's orientation before assuming it. On **7.x** storage is a table access
method, so `pg_am.amname` is `heap`, `ao_row` or `ao_column`:

```sql
-- 7.x
SELECT c.relname, am.amname, c.reloptions
FROM   pg_class c
LEFT   JOIN pg_am am ON am.oid = c.relam
WHERE  c.relname = 'fact_sales';
```

On **6.x** `pg_class.relam` is only meaningful for indexes; orientation lives in
`pg_appendonly.columnstore`, which 7.x removed from that catalog:

```sql
-- 6.x
SELECT c.relname, pa.columnstore, pa.compresstype, pa.compresslevel
FROM   pg_class c
JOIN   pg_appendonly pa ON pa.relid = c.oid
WHERE  c.relname = 'fact_sales';
```

Per-column compression settings are in `pg_attribute_encoding` on both lines.

Reference: [Table storage types in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/current/table_types.html)
