---
title: Distribute tables that join on the same key so the join is local
impact: CRITICAL
impactDescription: "A non-co-located join adds a Redistribute or Broadcast Motion that moves the whole join input across the interconnect on every execution"
tags: [schema, distribution, joins, motion]
---

## Distribute tables that join on the same key so the join is local

**Impact: CRITICAL**

A hash join can run entirely inside each segment only when both inputs are already hashed
on the join column. If they are not, the planner inserts a motion before the join:
`Redistribute Motion` rehashes one or both inputs across all segments, or
`Broadcast Motion` copies the whole smaller input to every segment. Both move data over
the interconnect on *every execution of the query*, and the cost scales with the data, not
with the schema. Co-location makes that cost zero and it costs nothing at all to arrange —
you just pick the same column.

`src/backend/cdb/cdbpathlocus.c` `cdbpathlocus_equal()` is the code that decides. Two
hashed loci are equal only when the distribution keys line up **positionally**, so
`DISTRIBUTED BY (a, b)` and `DISTRIBUTED BY (b, a)` do not co-locate, and a join that
equates only `a` does not co-locate with `DISTRIBUTED BY (a, b)` either — the whole key
must be equated.

**Incorrect (fact and dimension hashed on different columns):**

```sql
-- Bad: every orders x customers join redistributes orders on customer_id
CREATE TABLE customers (
    customer_id bigint NOT NULL,
    region_id   int,
    name        text
) DISTRIBUTED BY (customer_id);

CREATE TABLE orders (
    order_id    bigint NOT NULL,
    customer_id bigint NOT NULL,
    total       numeric(12,2)
) DISTRIBUTED BY (order_id);
```

**Correct (both hashed on the join column):**

```sql
-- Good: orders JOIN customers USING (customer_id) runs with no motion
CREATE TABLE customers (
    customer_id bigint NOT NULL,
    region_id   int,
    name        text
) DISTRIBUTED BY (customer_id);

CREATE TABLE orders (
    order_id    bigint NOT NULL,
    customer_id bigint NOT NULL,
    total       numeric(12,2)
) DISTRIBUTED BY (customer_id);
```

Confirm the motion is gone — a co-located join shows exactly one `Gather Motion` at the
top of the plan and no `Redistribute`/`Broadcast` under the join:

```sql
EXPLAIN SELECT c.region_id, sum(o.total)
FROM   orders o JOIN customers c USING (customer_id)
GROUP  BY 1;
```

When a fact table joins several dimensions, only one join can be co-located this way. Pick
the join that moves the most rows, and make the small dimensions
`DISTRIBUTED REPLICATED` instead (see `dist-replicated-for-small-dimensions`).

Reference: [Distribution in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/current/table_distribution.html)
