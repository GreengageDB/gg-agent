---
title: Rewrite correlated subqueries as joins before the planner has to
impact: HIGH
impactDescription: "A correlated subquery that cannot be decorrelated becomes a SubPlan executed once per outer row, or fails outright with 'correlated subquery with skip-level correlations is not supported'"
tags: [query-performance, sql, subquery, motion]
---

## Rewrite correlated subqueries as joins before the planner has to

**Impact: HIGH**

Both optimizers try to decorrelate a correlated subquery into a join. When they succeed,
the plan is a normal join and the cost is the usual Motion question. When they fail, the
subquery becomes a `SubPlan` node executed **once per outer row**, and every one of those
executions is CPU and latency the join form would not have spent.
`src/test/regress/expected/explain_analyze.out` shows exactly that shape:

```
 Gather Motion 3:1  (slice1; segments: 3) (actual rows=2 loops=1)
   ->  Seq Scan on slice_test a (actual rows=2 loops=1)
         Filter: ((j = (SubPlan 1)) AND ((SubPlan 1) = i))
         SubPlan 1
           ->  Result (actual rows=1 loops=78)
                 ->  Materialize (actual rows=1 loops=80)
                       ->  Broadcast Motion 3:3  (slice2; segments: 3) (actual rows=1 loops=1)
```

`loops=78` on the `Result` is the tell: 78 executions of the subquery for 78 outer rows.
On a million-row outer relation that is a million executions. Read the `loops=` on the
`Motion` separately — here it is `1`, because the `Materialize` above it caches the
broadcast result, so the interconnect is crossed once and the re-execution cost is local.
A `SubPlan` with no `Materialize` above its Motion re-runs the Motion per outer row, which
is the far more expensive shape.

Some correlations cannot be planned at all on distributed tables.
`src/backend/optimizer/plan/subselect.c` raises:

```
ERROR:  correlated subquery with skip-level correlations is not supported
```

That is a correlation reaching more than one query level up (an inner subquery referencing
the outermost query's columns) when a distributed relation is involved. There is no GUC to
turn it on — the query must be rewritten.

**Incorrect (a correlated scalar subquery in the target list):**

```sql
-- Bad: the subquery runs once per row of orders, and each run touches
-- line_items across the cluster.
SELECT o.order_id,
       (SELECT sum(l.amount) FROM line_items l WHERE l.order_id = o.order_id) AS total
FROM   orders o
WHERE  o.ordered_at >= DATE '2024-06-01';
```

**Correct (one aggregate pass, joined once):**

```sql
-- Good: line_items is aggregated once, and the join is co-located when both
-- tables are DISTRIBUTED BY (order_id).
SELECT o.order_id, l.total
FROM   orders o
LEFT   JOIN (SELECT order_id, sum(amount) AS total
             FROM   line_items
             GROUP  BY order_id) l
       ON l.order_id = o.order_id
WHERE  o.ordered_at >= DATE '2024-06-01';
```

The same rewrites apply to the other correlated forms: `WHERE EXISTS (...)` becomes a
semi-join, which both optimizers handle well and you should leave alone; `WHERE NOT EXISTS
(...)` becomes an anti-join, likewise; `WHERE col IN (SELECT ...)` with a correlation in
the inner query is the one to rewrite as an explicit join. A correlated subquery in a
`CASE` expression or in `ORDER BY` is the hardest for either optimizer and should always be
lifted out.

Read the plan to tell which case you are in: a `Nested Loop` or `Hash Join` means
decorrelation succeeded; a `SubPlan N` with `loops=` greater than 1 means it did not.

Reference: [How to analyze and optimize SQL queries](https://greengagedb.org/en/docs-gg/current/analyze_queries.html)
