---
title: Do not partition to fix skew — partitioning and distribution are orthogonal
impact: HIGH
impactDescription: "Every partition inherits the parent's distribution policy, so partitioning a skewed table produces many skewed partitions and no extra parallelism"
tags: [schema, partitioning, distribution, skew]
---

## Do not partition to fix skew — partitioning and distribution are orthogonal

**Impact: HIGH**

Distribution decides **which segment** a row lives on. Partitioning decides **which
physical relation inside that segment** it lives in. They compose: a table
`DISTRIBUTED BY (sale_id) PARTITION BY RANGE (sale_date)` with 24 segments and 36 monthly
partitions has 864 physical relations, and every one of them is hashed on `sale_id`.

The consequences people get wrong:

| Belief | Reality |
|---|---|
| "Partitioning will spread the data better" | No. Each partition carries the parent's distribution policy, so a skewed key stays skewed inside every partition |
| "Partitioning gives me more parallelism" | No. Parallelism is the segment count. Partitions are scanned by the same segments, serially within each |
| "Partitioning removes the motion in my join" | No. Motions are decided by the distribution policy; a partitioned table joins exactly like an unpartitioned one |
| "I can partition on one column and distribute on another" | Yes — and you should. That is the normal design |

What partitioning actually buys is **partition elimination** (the planner drops partitions
whose constraint contradicts the query predicate) and **O(1) data lifecycle**
(`DROP PARTITION`, `EXCHANGE PARTITION`). Both are worth having, neither is a skew fix.

**Incorrect (partitioning as a response to skew):**

```sql
-- Bad: region_code has 5 values, so 5 segments hold everything.
--      Partitioning by region does not change that at all.
CREATE TABLE sales_fact (
    sale_id     bigint NOT NULL,
    region_code text   NOT NULL,
    sale_date   date   NOT NULL,
    amount      numeric(12,2)
)
DISTRIBUTED BY (region_code)
PARTITION BY LIST (region_code)
( PARTITION emea VALUES ('EMEA'),
  PARTITION amer VALUES ('AMER'),
  PARTITION apac VALUES ('APAC'),
  DEFAULT PARTITION other );
```

**Correct (distribute for spread, partition for lifecycle and elimination):**

```sql
-- Good: sale_id spreads rows over every segment; sale_date drives elimination
--       and lets old months be dropped in one statement
CREATE TABLE sales_fact (
    sale_id     bigint NOT NULL,
    region_code text   NOT NULL,
    sale_date   date   NOT NULL,
    amount      numeric(12,2)
)
DISTRIBUTED BY (sale_id)
PARTITION BY RANGE (sale_date)
( START (date '2024-01-01') INCLUSIVE
  END   (date '2027-01-01') EXCLUSIVE
  EVERY (INTERVAL '1 month'),
  DEFAULT PARTITION other );
```

Confirm both decisions independently — skew per segment, and elimination per partition:

```sql
SELECT gp_segment_id, count(*) FROM sales_fact GROUP BY 1 ORDER BY 2 DESC;  -- skew
EXPLAIN SELECT sum(amount) FROM sales_fact WHERE sale_date >= date '2026-08-01';
```

Reference: [Partitioning in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/current/table_partitioning.html)
