---
title: Treat a large estimate-versus-actual gap as a statistics bug, not a planner bug
impact: HIGH
impactDescription: "Both optimizers pick Broadcast versus Redistribute from the estimated row count; a 100x underestimate turns a cheap plan into an N-fold data multiplication"
tags: [query-performance, plan, statistics, explain]
---

## Treat a large estimate-versus-actual gap as a statistics bug, not a planner bug

**Impact: HIGH**

Every `EXPLAIN ANALYZE` node prints `rows=<estimate>` in the cost group and
`rows=<actual>` in the actual group, and both are per-segment numbers below a Motion (see
`plan-actual-rows-are-segment-max`), so they compare directly. When the ratio exceeds
roughly 10x, the planner is not making a bad decision — it is making a correct decision
from wrong inputs, and no planner GUC will fix that.

The consequence is specific to MPP and expensive. The choice between `Broadcast Motion`
(send one side to every segment) and `Redistribute Motion` (rehash both sides) is driven
by the estimated size of the smaller input. An underestimate makes the optimizer broadcast
something huge; a `Broadcast Motion` over a table it thought had 1000 rows and actually has
50 million multiplies interconnect traffic by the segment count. Hash-join sizing has the
same dependency: an underestimated build side is sized for memory it does not need and
then spills.

Work upward from the leaf. The first node whose estimate is wrong is the one whose table
or column needs statistics; every node above it inherits the error.

**Incorrect (reaching for planner GUCs when the estimate is the problem):**

```sql
-- Bad: the estimate says 1 row, the reality is 4.2M. Disabling nested loops
-- just picks a different wrong plan from the same wrong numbers.
SET enable_nestloop = off;
EXPLAIN ANALYZE SELECT * FROM orders o JOIN order_lines l USING (order_id)
WHERE  o.status = 'shipped';
--  ->  Seq Scan on orders o  (cost=0.00..0.00 rows=1 width=48)
--        (actual time=0.03..812.4 rows=4200000 loops=1)
```

**Correct (fix the input, then re-plan):**

```sql
-- Good: refresh statistics for the columns the predicate and join use,
-- then re-read the same plan.
ANALYZE orders (status, order_id);
ANALYZE order_lines (order_id);

EXPLAIN ANALYZE SELECT * FROM orders o JOIN order_lines l USING (order_id)
WHERE  o.status = 'shipped';
```

If the gap survives a fresh `ANALYZE`, the estimate is failing for a structural reason,
not a staleness reason. The usual causes, in order of likelihood: correlated predicates on
two columns; a predicate on an expression rather than a bare column (statistics exist per
column, so `WHERE lower(status) = 'shipped'` has none); a join through a low-selectivity
`OR`; or `default_statistics_target` too low for a heavily skewed column, fixable per
column with `ALTER TABLE orders ALTER COLUMN status SET STATISTICS 250;` followed by
another `ANALYZE`.

Reference: [How to collect statistics via ANALYZE](https://greengagedb.org/en/docs-gg/current/statistics_analyze.html)
