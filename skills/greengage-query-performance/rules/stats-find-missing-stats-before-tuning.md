---
title: List tables with missing statistics before tuning a single query
impact: HIGH
impactDescription: "gp_toolkit.gp_stats_missing turns an open-ended plan investigation into a list of tables to ANALYZE, in one query"
tags: [query-performance, statistics, gp-toolkit, diagnosis]
---

## List tables with missing statistics before tuning a single query

**Impact: HIGH**

Two mechanisms will tell you which tables the optimizer is guessing about, and both are
cheaper than reading a plan.

GPORCA says so at query time. `src/backend/gpopt/utils/COptTasks.cpp` raises, at `NOTICE`
level and enabled by default (`optimizer_print_missing_stats` is `true`):

```
NOTICE:  One or more columns in the following table(s) do not have statistics: orders
HINT:  For non-partitioned tables, run analyze <table_name>(<column_list>). For
       partitioned tables, run analyze rootpartition <table_name>(<column_list>). See log
       for columns missing statistics.
```

The per-column detail goes to the server log as `Missing statistics for column: <rel>.<col>`
at `LOG` level, so `gplogfilter` or the segment logs have the exact column list.

`gp_toolkit.gp_stats_missing` answers the same question on demand, for every user table,
without running anything. Its columns are prefixed `smi`:

| Column | Meaning |
|---|---|
| `smischema`, `smitable` | the relation |
| `smisize` | `false` when `relpages = 0` or `reltuples = 0` — the table has never been analyzed or is empty |
| `smicols` | number of live columns in the table |
| `smirecs` | number of rows in `pg_statistic` for it; `0` means no statistics at all |

**Incorrect (reading plans one by one to find the blind spots):**

```sql
-- Bad: an open-ended hunt through plan output for estimates that look wrong.
EXPLAIN ANALYZE SELECT ...;
EXPLAIN ANALYZE SELECT ...;
```

**Correct (ask the catalog which tables have nothing, then fix those):**

```sql
-- Good: one query names every table the optimizer is guessing about.
SELECT smischema, smitable, smisize, smicols, smirecs
FROM   gp_toolkit.gp_stats_missing
WHERE  smirecs = 0 OR smirecs < smicols
ORDER  BY smischema, smitable;
```

```sql
-- Then fix them. Column lists keep the cost down on wide tables.
ANALYZE analytics.orders (customer_id, status, ordered_at);
```

`smirecs < smicols` is the partially-analyzed case: someone ran `ANALYZE tbl (col)` on one
column and the rest are still blind. `smisize = false` with `smirecs > 0` means statistics
exist but `relpages`/`reltuples` say the table is empty, which usually means the table was
truncated and reloaded without a re-`ANALYZE`.

On 7.x `gp_toolkit` is an extension; if the schema does not exist, run
`CREATE EXTENSION gp_toolkit;`. On 6.x it is installed into every database by `initdb`.

Reference: [Greengage DB system view: gp_stats_missing](https://greengagedb.org/en/docs-gg/current/reference/gp_toolkit/gp_stats_missing.html)
