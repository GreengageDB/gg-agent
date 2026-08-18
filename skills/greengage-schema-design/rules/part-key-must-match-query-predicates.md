---
title: Partition on the column your queries actually filter on
impact: HIGH
impactDescription: "Partition elimination only fires when a predicate constrains the partition key; a partition key nothing filters on adds catalog and planning cost for zero read savings"
tags: [schema, partitioning, partition-elimination, predicates]
---

## Partition on the column your queries actually filter on

**Impact: HIGH**

Partitioning pays for itself in exactly one way: the planner proves from the partition
constraint that a partition cannot contain any matching row, and skips scanning it. That
proof needs a predicate on the **partition key**. If your users filter on `sale_date` and
you partitioned on `region_code`, every query still scans every partition — you have added
catalog rows, locks and planning time for nothing.

Two things break elimination even when the key looks right:

- **A predicate the planner cannot compare to the constraint.** `WHERE
  to_char(sale_date, 'YYYY-MM') = '2026-08'` wraps the key in a function; the constraint
  is on `sale_date`, so nothing is eliminated. Write `WHERE sale_date >= date '2026-08-01'
  AND sale_date < date '2026-09-01'`.
- **A join predicate instead of a constant.** Elimination from a join is handled at
  execution time by a `Partition Selector` node rather than at plan time; a literal range
  is always the more reliable form.

Check, do not assume — read the plan and count the scans under the `Append`:

```sql
EXPLAIN SELECT sum(amount) FROM sales_fact
WHERE  sale_date >= date '2026-08-01' AND sale_date < date '2026-09-01';
```

On 6.x the plan prints a `Partitions selected: <n> (out of <m>)` line. On 7.x it lists
only the surviving partitions as children of the `Append`, plus a `Subplans Removed: <n>`
line when pruning happened at execution time
(`ExplainPropertyInteger("Subplans Removed", ...)`, `src/backend/commands/explain.c`).
Either way, if the child count equals the partition count, nothing was eliminated.

**Incorrect (partition key nobody filters on):**

```sql
-- Bad: reports are always "last N days", but the table is split by region
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

**Correct (partition key is the reporting filter; region stays an ordinary column):**

```sql
-- Good: a date range predicate touches only the months it needs
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

If two dimensions really are both filtered on every query — date and region, say — that is
what subpartitioning is for, but read `part-do-not-over-partition` before you reach for it:
36 months x 4 regions is 144 leaf relations per segment.

Reference: [Partitioning in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/current/table_partitioning.html)
