---
title: Give ANALYZE a column list on wide tables
impact: MEDIUM
impactDescription: "ANALYZE cost scales with column count; restricting it to join, filter and group columns cuts maintenance-window time without changing any plan"
tags: [query-performance, statistics, analyze, maintenance]
---

## Give `ANALYZE` a column list on wide tables

**Impact: MEDIUM**

`ANALYZE` samples rows on every segment and then computes a most-common-values list, a
histogram and a correlation figure **per column**. On a 300-column fact table that is 300
sorts of the sample, and the planner reads statistics for maybe a dozen of those columns —
the ones that appear in `WHERE`, `JOIN ... ON`, `GROUP BY` and `ORDER BY`. The rest are
paid for and never consulted.

The syntax is standard PostgreSQL and works on both lines:

```sql
ANALYZE <table> (<column> [, ...]);
```

The trade-off is real but narrow: a column with no statistics gets the planner's fixed
default selectivity, and GPORCA will name it in
`NOTICE: One or more columns in the following table(s) do not have statistics`. So restrict
the list to columns you are confident are never predicated on, and re-run a full `ANALYZE`
whenever the query mix changes.

**Incorrect (analyzing 300 columns to serve queries that use 8):**

```sql
-- Bad: full-width ANALYZE on a wide fact table, nightly.
ANALYZE analytics.fact_sales;
```

**Correct (analyze the columns the workload actually predicates on):**

```sql
-- Good: the join keys, the filter columns and the grouping columns.
ANALYZE analytics.fact_sales (
    customer_id, product_id, store_id,   -- join keys
    sale_date, channel, status,          -- filters
    region                               -- grouping
);
```

Find the list rather than guessing it — `pg_stats` shows which columns already carry
statistics, and `pg_stat_user_tables` plus your query log show which are used:

```sql
SELECT attname, n_distinct, correlation
FROM   pg_stats
WHERE  schemaname = 'analytics' AND tablename = 'fact_sales'
ORDER  BY attname;
```

`analyzedb` takes the same idea as `-i <col,col>` (include) and `-x <col,col>` (exclude),
but its own validation restricts them to one table at a time — combining either with `-s`
or `-f`, or using them with no `-t`, aborts with
`option -i or -x can only be used together with -t`. For a single column that needs *more* resolution
rather than less — a heavily skewed status column, say — raise its target instead of the
global one and re-analyze just that column:

```sql
ALTER TABLE analytics.fact_sales ALTER COLUMN status SET STATISTICS 250;
ANALYZE analytics.fact_sales (status);
```

Reference: [Overview of the ANALYZE SQL command](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/analyze.html)
