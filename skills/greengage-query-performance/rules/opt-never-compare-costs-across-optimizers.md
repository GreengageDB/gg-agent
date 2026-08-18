---
title: Never compare cost numbers between GPORCA and the Postgres planner
impact: HIGH
impactDescription: "The two optimizers are separate code bases with separate cost models; choosing a plan by its lower cost number picks arbitrarily and can be 10x wrong"
tags: [query-performance, optimizer, gporca, cost]
---

## Never compare cost numbers between GPORCA and the Postgres planner

**Impact: HIGH**

Greengage ships two independent optimizers: GPORCA (`src/backend/gporca/`, C++, selected
by `optimizer = on`, the default in any `USE_ORCA` build) and the PostgreSQL planner
extended with MPP motion planning (`src/backend/optimizer/`, selected by
`optimizer = off`). They are not two strategies inside one planner. They have separate
cost models, separate calibration, and separate notions of what a cost unit represents —
`optimizer_cost_model` alone offers `legacy`, `calibrated` (the 7.x default) and
`experimental` for GPORCA, none of which correspond to the Postgres planner's page-fetch
units.

The practical consequence is that `cost=0.00..73.50` from one optimizer and
`cost=0.00..2841.19` from the other say nothing about which plan is faster. The comparison
is not "approximately valid" or "valid within an order of magnitude" — it is meaningless,
in the same way as comparing a price in one currency to a price in another without a rate.

Costs are also **per-slice, per-segment** on both optimizers, so they are not comparable to
a single-node PostgreSQL plan for the same data either.

**Incorrect (choosing an optimizer by its cost number):**

```sql
-- Bad: two numbers from two different scales. This decides nothing.
SET optimizer = on;
EXPLAIN SELECT * FROM orders o JOIN customers c USING (customer_id);
--  Gather Motion 3:1  (slice1; segments: 3)  (cost=0.00..1293.00 rows=1000 width=24)
--  Optimizer: GPORCA

SET optimizer = off;
EXPLAIN SELECT * FROM orders o JOIN customers c USING (customer_id);
--  Gather Motion 3:1  (slice2; segments: 3)  (cost=25.50..73.50 rows=1000 width=24)
--  Optimizer: Postgres-based planner
-- "off is 17x cheaper" -- no, it is a different unit.
```

**Correct (compare shape and measured time, with costs suppressed):**

```sql
-- Good: COSTS OFF removes the temptation entirely, and ANALYZE supplies the
-- only number that is comparable - milliseconds.
SET optimizer = on;
EXPLAIN (ANALYZE, COSTS OFF) SELECT * FROM orders o JOIN customers c USING (customer_id);

SET optimizer = off;
EXPLAIN (ANALYZE, COSTS OFF) SELECT * FROM orders o JOIN customers c USING (customer_id);

RESET optimizer;
```

What *is* comparable across optimizers, and worth reading: the number and type of Motions,
the join order and join methods, the number of slices, whether a node spilled, and
`Execution Time:`. See `opt-compare-optimizers-by-measuring-both` for the full procedure.

Reference: [Server configuration parameters (GUCs) overview](https://greengagedb.org/en/docs-gg/current/reference/guc_reference.html)
