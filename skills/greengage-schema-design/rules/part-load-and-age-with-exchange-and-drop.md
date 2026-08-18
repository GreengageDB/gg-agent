---
title: Load and age partitioned data with EXCHANGE and DROP PARTITION, never with DELETE
impact: MEDIUM-HIGH
impactDescription: "DROP PARTITION unlinks files in constant time; the equivalent DELETE scans the table, writes a visimap entry per row and leaves the space occupied until VACUUM"
tags: [schema, partitioning, maintenance, etl, lifecycle]
---

## Load and age partitioned data with EXCHANGE and DROP PARTITION, never with DELETE

**Impact: MEDIUM-HIGH**

The main operational reason to partition is that the data lifecycle becomes metadata work.
`ALTER TABLE ... DROP PARTITION` removes a relation; the cost does not depend on how many
rows were in it. `DELETE FROM sales_fact WHERE sale_date < ...` scans, marks and — on an
append-optimized table — leaves every deleted row on disk until `VACUUM` crosses
`gp_appendonly_compaction_threshold` (see `store-vacuum-after-ao-dml`).

The same argument applies to loading. The documentation states the pattern outright: "The
best practice for loading data into partitioned tables is using partition exchange." You
build the new data in a standalone table, validate it there, then swap it in as a
partition in one transactional DDL statement — the live table is never half-loaded.

The classic-syntax maintenance verbs, all on both 6.x and 7.x:

| Operation | Statement |
|---|---|
| Add a partition | `ALTER TABLE t ADD PARTITION p START (date '2026-09-01') END (date '2026-10-01') EXCLUSIVE;` |
| Swap data in | `ALTER TABLE t EXCHANGE PARTITION FOR (date '2026-08-15') WITH TABLE t_staging;` |
| Split a partition | `ALTER TABLE t SPLIT PARTITION p AT (date '2026-08-15') INTO (PARTITION p1, PARTITION p2);` |
| Drop old data | `ALTER TABLE t DROP PARTITION FOR (date '2024-01-15');` |
| Change the template | `ALTER TABLE t SET SUBPARTITION TEMPLATE ( ... );` |

The exchange candidate must match the partition's column list. It does **not** have to
match its storage: `src/test/regress/sql/partition_storage.sql` exchanges heap for AO row
and AO row for AO column in the same table, which is how you compress historical
partitions while the current one stays heap.

**Incorrect (DELETE-based retention on a partitioned AO table):**

```sql
-- Bad: full scan, one visimap write per row, and the space stays allocated
DELETE FROM sales_fact WHERE sale_date < date '2025-01-01';
```

**Correct (drop the partitions, and load by exchange):**

```sql
-- Good: retention is a metadata operation
ALTER TABLE sales_fact DROP PARTITION FOR (date '2024-01-15');

-- Good: load into a standalone table, validate, then swap it in atomically
CREATE TABLE sales_fact_20260815 (LIKE sales_fact)
  USING ao_column
  WITH (compresstype=zstd, compresslevel=5)
  DISTRIBUTED BY (sale_id);

INSERT INTO sales_fact_20260815 SELECT * FROM stg_sales WHERE sale_date = date '2026-08-15';
ANALYZE sales_fact_20260815;

ALTER TABLE sales_fact
  EXCHANGE PARTITION FOR (date '2026-08-15') WITH TABLE sales_fact_20260815;
```

After the exchange, `sales_fact_20260815` holds whatever was in the partition before — drop
it or keep it as the rollback copy.

Reference: [Partitioning in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/current/table_partitioning.html)
