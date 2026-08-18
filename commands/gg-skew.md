---
description: Report data and computational skew across Greengage segments for a table, schema, or database
argument-hint: "[table, schema, or nothing for the whole database]"
---

Report distribution skew for: $ARGUMENTS

Load the **greengage-query-performance** skill for how to interpret the numbers, and
**greengage-schema-design** for what to do about them.

Skew is the characteristic MPP failure: a cluster with an unevenly distributed table runs
at the speed of its busiest segment, so 23 of 24 segments idle while one does all the
work. It shows up as a query that is slow for no visible reason in the plan.

## Collect

**Per-table row distribution** — the direct measurement, and the one to lead with. For a
named table:

```sql
SELECT gp_segment_id, count(*) AS rows
  FROM <table>
 GROUP BY 1
 ORDER BY 2 DESC;
```

Report the ratio of the largest segment to the mean, not just the raw counts. A handful of
percent is normal; a segment holding several times the mean is a problem.

**Cluster-wide skew coefficients** — a coefficient of variation per table:

```sql
SELECT * FROM gp_toolkit.gp_skew_coefficients ORDER BY skccoeff DESC;
```

**Computational skew** — segments idling while others work, which can happen even when
storage is evenly distributed:

```sql
SELECT * FROM gp_toolkit.gp_skew_idle_fractions ORDER BY siffraction DESC;
```

Both of these scan every table in the database. On a large cluster say so and get
confirmation before running them; scope to a schema or a table list instead when you can.

**Context for each skewed table** — its distribution policy and size, so the report says
*why*:

```sql
SELECT c.relname,
       pg_get_table_distributedby(c.oid) AS distributed_by
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname NOT IN ('pg_catalog','information_schema','gp_toolkit');
```

Plus `gp_toolkit.gp_size_of_table_disk` for the tables that matter.
`pg_get_table_distributedby(oid)` exists on both the 6.x and 7.x lines; the raw policy is
in `gp_distribution_policy` if you need the key column numbers rather than the clause.

## Report

Rank tables by how much their skew actually costs — a badly skewed 10-row lookup table is
noise, a mildly skewed fact table is not. For each one worth acting on: the current
distribution key, why it skews (low cardinality, a dominant value, many NULLs, a
correlated key), and the candidate replacement.

Be explicit that changing a distribution key rewrites the table, and that
`DISTRIBUTED RANDOMLY` fixes skew at the cost of forcing motions on joins —
`DISTRIBUTED REPLICATED` is often the better answer for small dimension tables. Do not run
the `ALTER TABLE` yourself unless asked.
