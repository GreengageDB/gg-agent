---
title: Do not use the same column as both the distribution key and the partition key
impact: MEDIUM-HIGH
impactDescription: "Each partition then holds only the rows for one key value range, so a single partition lives on a handful of segments and every query on it runs at a fraction of cluster width"
tags: [schema, partitioning, distribution, skew]
---

## Do not use the same column as both the distribution key and the partition key

**Impact: MEDIUM-HIGH**

Distribution hashes the column to pick a segment; partitioning ranges or lists the same
column to pick a relation. If both use `region_code`, then every row in the `EMEA`
partition has `region_code = 'EMEA'`, hashes to the same value, and therefore lands on
**one segment**. The partition exists on 24 segments but 23 of them hold an empty relation.
A query with `WHERE region_code = 'EMEA'` then eliminates down to that one partition and
runs single-segment.

This is the pathological form of `dist-high-cardinality-key`: the partition constraint
collapses the distribution key's cardinality to one value per partition. Range
partitioning on a distributed date column has the same effect a partition at a time.

The two keys should answer two different questions:

| Key | Answers | Wants |
|---|---|---|
| Distribution | "which segment?" | high cardinality, even frequency, immutable |
| Partition | "which slice do I drop or skip?" | matches query predicates, matches retention grain, coarse |

**Incorrect (same column for both):**

```sql
-- Bad: partition emea holds only region_code='EMEA', so it lives on one segment
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

**Correct (independent keys):**

```sql
-- Good: every partition is spread over all segments by sale_id
CREATE TABLE sales_fact (
    sale_id     bigint NOT NULL,
    region_code text   NOT NULL,
    sale_date   date   NOT NULL,
    amount      numeric(12,2)
)
DISTRIBUTED BY (sale_id)
PARTITION BY LIST (region_code)
( PARTITION emea VALUES ('EMEA'),
  PARTITION amer VALUES ('AMER'),
  PARTITION apac VALUES ('APAC'),
  DEFAULT PARTITION other );
```

Verify per-partition spread, not just per-table spread — a table can look even in
aggregate while every individual partition is single-segment:

```sql
SELECT tableoid::regclass AS partition, gp_segment_id, count(*)
FROM   sales_fact
GROUP  BY 1, 2
ORDER  BY 1, 3 DESC;
```

Reference: [Partitioning in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/current/table_partitioning.html)
