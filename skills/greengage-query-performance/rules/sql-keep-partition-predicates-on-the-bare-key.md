---
title: Write partition predicates against the bare partition key
impact: HIGH
impactDescription: "A function or cast around the partition key disables partition elimination, turning a one-partition scan into a scan of every partition on every segment"
tags: [query-performance, sql, partitioning, pruning]
---

## Write partition predicates against the bare partition key

**Impact: HIGH**

Partition elimination works by comparing the predicate against each partition's boundary
constraint. That comparison only happens when the predicate is of the form
`<partition_key> <operator> <constant-or-parameter>`. Wrap the key in `date_trunc()`,
`to_char()`, `extract()` or a cast, and there is nothing left to match: the plan scans
every partition, on every segment.

Two things to read in the plan. Plan-time elimination shows up as a shorter `Append` list
— fewer child scans than there are partitions. Run-time elimination, which handles
predicates whose value is only known at execution (`now()`, a parameter, a subquery
result), shows up in `EXPLAIN ANALYZE` as `Subplans Removed: N` and, under GPORCA, as
`Partition Selector` and `Dynamic Seq Scan` nodes.

**Incorrect (a function around the partition key):**

```sql
-- Bad: sale_date is the partition key, but date_trunc() hides it, so every
-- monthly partition is scanned.
CREATE TABLE fact_sales (sale_id bigint, sale_date date, amount numeric)
DISTRIBUTED BY (sale_id)
PARTITION BY RANGE (sale_date)
( START (DATE '2024-01-01') END (DATE '2025-01-01') EVERY (INTERVAL '1 month') );

EXPLAIN (COSTS OFF)
SELECT sum(amount) FROM fact_sales
WHERE  date_trunc('month', sale_date) = DATE '2024-06-01';
```

**Correct (a half-open range on the bare column):**

```sql
-- Good: the predicate is directly comparable to each partition's boundary,
-- so only the June partition appears in the plan.
EXPLAIN (COSTS OFF)
SELECT sum(amount) FROM fact_sales
WHERE  sale_date >= DATE '2024-06-01'
AND    sale_date <  DATE '2024-07-01';
```

The same shape covers the other common offenders. Replace
`extract(year FROM sale_date) = 2024` with a range over the year; replace
`sale_date::text LIKE '2024-06%'` with a range; and when the partition key is a
`timestamp` but you filter with a `date`, write the bounds as timestamps so no cast is
introduced on the column side. Casting the **constant** is free — casting the **column** is
what breaks elimination.

7.x carries both partitioning grammars: the classic `PARTITION BY ... SUBPARTITION
TEMPLATE` form shown above and PostgreSQL declarative partitioning
(`PARTITION BY RANGE (sale_date)` with explicit `CREATE TABLE ... PARTITION OF`). Both
prune on the same rule. 6.x has only the classic form.

Reference: [Partitioning in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/current/table_partitioning.html)
