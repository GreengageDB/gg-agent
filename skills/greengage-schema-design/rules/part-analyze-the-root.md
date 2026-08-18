---
title: ANALYZE the root of a partitioned table, not only the partitions you loaded
impact: MEDIUM
impactDescription: "The planner costs a partitioned scan from the root's statistics; stale root stats produce wrong join orders across the whole table even when every leaf is freshly analyzed"
tags: [schema, partitioning, statistics, analyze, planner]
---

## ANALYZE the root of a partitioned table, not only the partitions you loaded

**Impact: MEDIUM**

A partitioned table's plan is costed from statistics on the **root** relation, which are
gathered separately from the leaves. An ETL job that loads one partition and runs
`ANALYZE sales_fact_1_prt_202608` leaves the root's row count, distinct counts and
histograms describing the table as it was months ago — so the planner's estimate of how
many rows a scan of `sales_fact` returns can be off by orders of magnitude, and it picks
the wrong join order and the wrong motion.

Two GUCs govern which levels get analyzed, both `PGC_USERSET`, with the same values on 6.x
and 7.x (`src/backend/utils/misc/guc_gp.c`):

| GUC | Default | Effect |
|---|---|---|
| `optimizer_analyze_root_partition` | `true` | "Enable statistics collection on root partitions during ANALYZE" |
| `optimizer_analyze_midlevel_partition` | **`false`** | "Enable statistics collection on intermediate partitions during ANALYZE" — off by default, so a multi-level hierarchy gets leaf and root stats but nothing in between |

Because `optimizer_analyze_root_partition` is `PGC_USERSET`, a job that turns it off "for
speed" silently produces the stale-root situation for everything it touches.

**Incorrect (analyze the loaded leaf only):**

```sql
-- Bad: the root's statistics still describe last month's table
INSERT INTO sales_fact SELECT * FROM stg_sales WHERE sale_date >= date '2026-08-01';
ANALYZE sales_fact_1_prt_202608;
```

**Correct (analyze the root, which also refreshes what the planner costs from):**

```sql
-- Good: ANALYZE on the parent gathers leaf and root statistics
INSERT INTO sales_fact SELECT * FROM stg_sales WHERE sale_date >= date '2026-08-01';
ANALYZE sales_fact;
```

For a large hierarchy where a full `ANALYZE` is too slow every night, use `analyzedb`,
which tracks which partitions changed and only re-analyzes those plus the root:

```sh
analyzedb -d analytics -t public.sales_fact
```

Check for tables the planner has no statistics for at all:

```sql
-- smirecs = 0 means pg_statistic has no rows at all for that table
SELECT smischema, smitable, smicols, smirecs
FROM   gp_toolkit.gp_stats_missing
WHERE  smirecs = 0
ORDER  BY 1, 2;
```

Reference: [How to collect statistics via ANALYZE](https://greengagedb.org/en/docs-gg/current/statistics_analyze.html)
