---
title: Never distribute on a date, timestamp or load-batch column
impact: HIGH
impactDescription: "Time-shaped keys concentrate every day's load onto one segment, so ingestion and any date-filtered scan run single-segment while the rest of the cluster idles"
tags: [schema, distribution, skew, time-series]
---

## Never distribute on a date, timestamp or load-batch column

**Impact: HIGH**

The instinct is imported from single-node PostgreSQL, where clustering on time is good
because it makes ranges contiguous. In an MPP cluster it is the opposite: a distribution
key exists to spread rows, and time-shaped data does not arrive spread out. A day's worth
of rows all share the same `sale_date`, so they all hash to the same segment — that
segment does all the writing during the load, and any query with
`WHERE sale_date = current_date` runs on exactly one segment while the rest wait. A
timestamp with microsecond resolution spreads better but still ties one *slice of time* to
one segment, which is exactly the slice most queries ask for.

The documentation is explicit that dates and timestamps are poor keys. Time belongs in the
**partition** key, which is a different mechanism entirely (see `part-is-not-distribution`)
and does exactly what the instinct wants.

**Incorrect (time as the distribution key):**

```sql
-- Bad: all of today's rows land on one segment; tomorrow's land on another
CREATE TABLE sales_fact (
    sale_id     bigint NOT NULL,
    sale_date   date   NOT NULL,
    store_id    int,
    amount      numeric(12,2)
)
DISTRIBUTED BY (sale_date);
```

**Correct (spread on identity, split on time):**

```sql
-- Good: sale_id spreads writes and scans over every segment;
--       sale_date drives partition elimination inside each segment
CREATE TABLE sales_fact (
    sale_id     bigint NOT NULL,
    sale_date   date   NOT NULL,
    store_id    int,
    amount      numeric(12,2)
)
DISTRIBUTED BY (sale_id)
PARTITION BY RANGE (sale_date)
( START (date '2026-01-01') INCLUSIVE
  END   (date '2027-01-01') EXCLUSIVE
  EVERY (INTERVAL '1 month'),
  DEFAULT PARTITION other );
```

The same argument rules out `load_batch_id`, `etl_run_id`, `insert_ts` and any other
column whose value is constant for one load: they are all time in disguise.

Reference: [Distribution in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/current/table_distribution.html)
