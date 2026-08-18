---
title: Add indexes only for selective lookups, never as a reflex on an analytical table
impact: MEDIUM-HIGH
impactDescription: "Every index slows the load, and on an append-optimized table the first index also forces a block directory; a low-selectivity index is a pure cost on a scan-heavy workload"
tags: [schema, indexes, append-optimized, performance]
---

## Add indexes only for selective lookups, never as a reflex on an analytical table

**Impact: MEDIUM-HIGH**

In a single-node database an extra index is cheap insurance. In an MPP cluster it usually
is not. A sequential scan of a compressed, column-oriented table is already split across
every segment and reads only the columns the query names, so a query returning any
meaningful fraction of the table is faster scanning than seeking. An index earns its place
only for genuinely selective predicates — a handful of rows out of billions.

The costs, in order of how often they bite:

| Cost | Detail |
|---|---|
| Load throughput | Every index is maintained on every `INSERT`, on every segment |
| Block directory | The first index on an append-optimized table forces creation of the aoblkdir auxiliary relation (relkind `'b'`); `src/backend/commands/indexcmds.c` notes creating and maintaining it "is expensive" and delays it until an index actually exists |
| Rebuild on rewrite | `ALTER TABLE ... SET DISTRIBUTED BY` and `SET ACCESS METHOD` rebuild every index |
| Storage | Multiplied by the segment count and by the partition count |

Index-type notes specific to Greengage:

- `bitmap` is an extra access method (`src/include/catalog/pg_am.dat`), suited to
  low-cardinality columns queried in combination. It does not support
  `CREATE INDEX CONCURRENTLY`: `ERROR: CONCURRENTLY is not supported when creating bitmap indexes`.
- Unique indexes on append-optimized tables: **not possible on 6.x**
  (`ERROR: append-only tables do not support unique indexes`); possible on 7.x but not
  `CONCURRENTLY` (`ERROR: append-only tables do not support unique indexes built concurrently`).
- Any unique index, on any storage, is still bound by
  `dist-unique-keys-must-contain-distkey`.

**Incorrect (PostgreSQL reflex: index every join and filter column):**

```sql
-- Bad: five indexes on a nightly-loaded fact table, none of them selective
CREATE INDEX ON sales_fact (sale_date);
CREATE INDEX ON sales_fact (region_code);
CREATE INDEX ON sales_fact (store_id);
CREATE INDEX ON sales_fact (product_id);
CREATE INDEX ON sales_fact (sale_id);
```

**Correct (partition for the range filter, index only the point lookup):**

```sql
-- Good: sale_date is the partition key, so range queries eliminate partitions
--       with no index at all
CREATE TABLE sales_fact (
    sale_id     bigint NOT NULL,
    sale_date   date   NOT NULL,
    region_code text   NOT NULL,
    amount      numeric(12,2)
)
USING ao_column
DISTRIBUTED BY (sale_id)
PARTITION BY RANGE (sale_date)
( START (date '2024-01-01') INCLUSIVE
  END   (date '2027-01-01') EXCLUSIVE
  EVERY (INTERVAL '1 month'),
  DEFAULT PARTITION other );

-- Good: one index, for the one access path that is a true point lookup
CREATE INDEX sales_fact_sale_id_idx ON sales_fact (sale_id);
```

Before adding an index, prove the scan is the problem:

```sql
EXPLAIN ANALYZE SELECT * FROM sales_fact WHERE sale_id = 918273645;
```

And inventory what is already there, with what it costs on disk (do not use
`pg_stat_all_indexes` for this — on the coordinator its counters describe coordinator
activity, not the segment scans that actually run):

```sql
SELECT ti.titablename, ti.tiindexname,
       pg_size_pretty(sotaid.sotaididxsize) AS all_indexes_on_table
FROM   gp_toolkit.gp_table_indexes ti
JOIN   gp_toolkit.gp_size_of_table_and_indexes_disk sotaid
       ON sotaid.sotaidoid = ti.tireloid
WHERE  ti.titablename LIKE 'sales_fact%'
ORDER  BY 1, 2;
```

Reference: [What are indexes, their purpose, limitations](https://greengagedb.org/en/docs-gg/current/indexes.html)
