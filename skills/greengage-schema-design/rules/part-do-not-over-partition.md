---
title: Count leaf relations before you partition, and multiply by the segment count
impact: HIGH
impactDescription: "Partition count multiplies with segment count and column count; thousands of tiny relations slow planning, vacuum, recovery and expansion far more than they speed scans"
tags: [schema, partitioning, catalog, planning, operations]
---

## Count leaf relations before you partition, and multiply by the segment count

**Impact: HIGH**

The number you have to reason about is not "how many partitions" — it is

```
leaf partitions  x  primary segments  x  (columns, if AO column-oriented)
```

Daily partitions for three years is 1095 leaves. On 24 segments that is 26 280 relations.
As `ao_column` with 40 columns it is over a million physical files. The documentation is
blunt: "Avoid creating more partitions than necessary. Excessive partitioning can
negatively impact system operations such as vacuuming, segment recovery, cluster
expansion, disk usage checks, and others."

Concretely, the costs are:

| Cost | Why |
|---|---|
| Planning time | The planner must consider and lock every partition before pruning |
| Lock table pressure | Each partition takes its own lock, on the coordinator and on every segment |
| Catalog size | `pg_class`, `pg_attribute`, `pg_inherits`, plus AO aux relations (`'o'` aoseg, `'b'` aoblkdir, `'M'` aovisimap) per leaf |
| `ANALYZE` cost | Statistics are gathered per leaf, and again for the root |
| Operations | `gpexpand`, `gprecoverseg`, `gpcheckcat` and disk-usage checks all walk the whole catalog |

7.x has a guard rail for hierarchy depth: `gp_max_partition_level`
("Sets the maximum number of levels allowed when creating a partitioned table using
Greengage classic syntax", default `0` = no limit, `PGC_SUSET`). There is no equivalent
guard on partition *count* — that is your job.

Pick the coarsest granularity that still gives elimination and a workable lifecycle.
Monthly partitions for a table queried by month, with old months dropped yearly, is
almost always right; daily partitions are right only when the load and retention grain is
genuinely a day.

**Incorrect (daily partitions subpartitioned by region, kept for three years):**

```sql
-- Bad: 1095 x 4 = 4380 leaves, times the segment count, times the column count
CREATE TABLE sales_fact (
    sale_id bigint NOT NULL, region_code text NOT NULL,
    sale_date date NOT NULL, amount numeric(12,2)
)
USING ao_column
DISTRIBUTED BY (sale_id)
PARTITION BY RANGE (sale_date)
  SUBPARTITION BY LIST (region_code)
    SUBPARTITION TEMPLATE
    ( SUBPARTITION emea VALUES ('EMEA'),
      SUBPARTITION amer VALUES ('AMER'),
      SUBPARTITION apac VALUES ('APAC'),
      DEFAULT SUBPARTITION other )
( START (date '2024-01-01') INCLUSIVE
  END   (date '2027-01-01') EXCLUSIVE
  EVERY (INTERVAL '1 day') );
```

**Correct (monthly, single level — 36 leaves):**

```sql
-- Good: elimination on the reporting grain, one DROP PARTITION per month of retention
CREATE TABLE sales_fact (
    sale_id bigint NOT NULL, region_code text NOT NULL,
    sale_date date NOT NULL, amount numeric(12,2)
)
USING ao_column
DISTRIBUTED BY (sale_id)
PARTITION BY RANGE (sale_date)
( START (date '2024-01-01') INCLUSIVE
  END   (date '2027-01-01') EXCLUSIVE
  EVERY (INTERVAL '1 month'),
  DEFAULT PARTITION other );
```

Count what you already have before adding more:

```sql
SELECT count(*) AS leaf_relations
FROM   pg_class     c
JOIN   pg_inherits  i ON i.inhrelid = c.oid
WHERE  c.relkind = 'r'
  AND  NOT EXISTS (SELECT 1 FROM pg_inherits ii WHERE ii.inhparent = c.oid);
```

Reference: [Partitioning in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/current/table_partitioning.html)
