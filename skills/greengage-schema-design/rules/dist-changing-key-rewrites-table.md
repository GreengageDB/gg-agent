---
title: Budget a full redistribution before changing a distribution key
impact: HIGH
impactDescription: "ALTER TABLE SET DISTRIBUTED BY rewrites every row and moves it across the interconnect while holding an exclusive lock; on a terabyte fact table that is hours of downtime"
tags: [schema, distribution, alter-table, migration]
---

## Budget a full redistribution before changing a distribution key

**Impact: HIGH**

`ALTER TABLE ... SET DISTRIBUTED BY (...)` is not a catalog update. Greengage builds a new
relfilenode, rehashes every row on the new key, ships each row to its new segment and
swaps the files, under an exclusive lock. Cost is proportional to table size plus
interconnect throughput, not to how many rows change segment. Indexes are rebuilt too.
This is why `dist-always-write-explicit-clause` matters: fixing the key later costs orders
of magnitude more than choosing it up front.

Two behaviours surprise people:

**Re-stating the same key does nothing.** `src/backend/commands/tablecmds.c` compares the
new policy to the old one and, if identical, warns and returns without touching data:

```
WARNING:  distribution policy of relation "orders" already set to (order_id)
HINT:  Use ALTER TABLE "orders" SET WITH (REORGANIZE=TRUE) DISTRIBUTED BY (order_id) to force redistribution
```

`SET WITH (REORGANIZE=true)` is therefore the way to force a rewrite that only rebalances
data — after `gpexpand`, or to clear bloat — without changing the key at all.

**Existing constraints veto the change.** On 7.x the new policy is checked against every
unique index before anything moves, so you get
`distribution policy is not compatible with the table's PRIMARY KEY` up front rather than
half way through (6.x has no such re-check on `SET DISTRIBUTED BY` — it only validates the
policy when the index is created). On both lines you must not name a system column:
`cannot distribute by system column "gp_segment_id"`.

**Incorrect (assuming it is a metadata change, run inside a maintenance window sized for one):**

```sql
-- Bad: treated as instant; actually rewrites and reships the whole table
ALTER TABLE sales_fact SET DISTRIBUTED BY (customer_id);
```

**Correct (verify the constraint fit first, then rewrite deliberately):**

```sql
-- 1. Check what would block the change: every unique index must contain customer_id
SELECT i.indexrelid::regclass AS index_name, i.indisunique, i.indisprimary
FROM   pg_index i
WHERE  i.indrelid = 'sales_fact'::regclass
  AND  (i.indisunique OR i.indisprimary);

-- 2. Confirm the current key and size before committing to the rewrite
SELECT pg_catalog.pg_get_table_distributedby('sales_fact'::regclass),
       pg_size_pretty(pg_total_relation_size('sales_fact'));

-- 3. Redistribute (exclusive lock, full rewrite)
ALTER TABLE sales_fact SET DISTRIBUTED BY (customer_id);

-- 4. The rewrite swaps in a new relfilenode with swap_stats=false
--    (src/backend/commands/tablecmds.c), so pg_class.relpages/reltuples are stale
ANALYZE sales_fact;
```

To force a rebalance without changing the key — restate the key the table already has:

```sql
ALTER TABLE sales_fact SET WITH (REORGANIZE=true) DISTRIBUTED BY (customer_id);
```

Reference: [Overview of the ALTER TABLE SQL command](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/alter_table.html)
