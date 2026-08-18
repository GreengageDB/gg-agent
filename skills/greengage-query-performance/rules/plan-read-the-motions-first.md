---
title: Read the Motion nodes before the scans and joins
impact: CRITICAL
impactDescription: "A Broadcast Motion on a large table multiplies data volume by the segment count; finding it is usually a bigger win than any scan or join change"
tags: [query-performance, plan, motion, interconnect]
---

## Read the Motion nodes before the scans and joins

**Impact: CRITICAL**

`Motion` is the only node type that moves data between processes over the interconnect,
and it is the only node type PostgreSQL never had. Everything else in the plan is local
work that a segment does on its own slice of the data. There are five spellings, produced
in `src/backend/commands/explain.c`:

| Plan text | What happens | Typical cost |
|---|---|---|
| `Gather Motion N:1` | every segment sends its rows to the single coordinator process | serialisation point; fine for aggregates, fatal for full result sets |
| `Redistribute Motion N:N` | every segment rehashes its rows on the `Hash Key` and sends each to its new owner | one full pass of that input over the network |
| `Broadcast Motion N:N` | every segment sends **all** its rows to **all** segments | input volume multiplied by N; only sane for small inputs |
| `Explicit Redistribute Motion` | rows routed to a specific segment by `gp_segment_id`, used by `UPDATE`/`DELETE` | one pass, DML only |
| `Explicit Gather Motion N:1` | the subplan runs on N segments but only **one** of them sends its rows | appears above a replicated-locus subtree, where a plain gather would return N copies of every row |

The `N:M` numbers are senders:receivers. `Gather Motion 3:1` means three segment processes
feeding one coordinator process. A `Hash Key:` line under a `Redistribute Motion` names
the columns being rehashed, and a `Merge Key:` line under a `Gather Motion` means the
coordinator is merging pre-sorted streams instead of just concatenating them.

**Incorrect (join key is neither table's distribution key, so both sides move):**

```sql
-- Bad: orders is distributed by order_id, customers by customer_id.
-- The join is on customer_id, so orders must be rehashed on every execution.
CREATE TABLE orders    (order_id bigint, customer_id bigint, total numeric)
  DISTRIBUTED BY (order_id);
CREATE TABLE customers (customer_id bigint, region text)
  DISTRIBUTED BY (customer_id);

EXPLAIN SELECT c.region, sum(o.total)
FROM   orders o JOIN customers c USING (customer_id)
GROUP  BY c.region;
-- ->  Redistribute Motion 3:3  (slice2; segments: 3)
--       Hash Key: o.customer_id
```

**Correct (co-located join, no Motion under the join):**

```sql
-- Good: distributing orders by customer_id co-locates the join; the plan keeps
-- only the final Gather Motion, and the interconnect carries aggregate rows.
CREATE TABLE orders (order_id bigint, customer_id bigint, total numeric)
  DISTRIBUTED BY (customer_id);

EXPLAIN SELECT c.region, sum(o.total)
FROM   orders o JOIN customers c USING (customer_id)
GROUP  BY c.region;
```

Count the Motions in the plan you are tuning, and for each one ask what would have to be
true for it to disappear. A `Broadcast Motion` over anything bigger than a dimension table
is the single highest-value finding in an MPP plan.

Reference: [How to analyze and optimize SQL queries](https://greengagedb.org/en/docs-gg/current/analyze_queries.html)
