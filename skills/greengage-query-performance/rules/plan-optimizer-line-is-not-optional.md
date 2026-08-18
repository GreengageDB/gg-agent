---
title: Read the Optimizer line on every plan
impact: CRITICAL
impactDescription: "GPORCA falls back to the Postgres planner silently, so an entire tuning session can be spent testing an optimizer that never ran"
tags: [query-performance, plan, optimizer, gporca]
---

## Read the `Optimizer:` line on every plan

**Impact: CRITICAL**

`EXPLAIN` prints one line at the end of the plan tree naming the optimizer that actually
produced it. This is not decoration: `optimizer = on` requests GPORCA, it does not
guarantee it. When GPORCA cannot translate a query it throws, the exception is caught in
`src/backend/gpopt/CGPOptimizer.cpp`, and the Postgres planner produces the plan instead.
The explanatory `INFO` message is gated on `optimizer_trace_fallback`, which defaults to
`false`, so by default nothing is said.

The exact strings differ between lines — grep for the pair your cluster prints:

| Line | 7.x | 6.x |
|---|---|---|
| Postgres planner | `Optimizer: Postgres-based planner` | `Optimizer: Postgres query optimizer` |
| GPORCA | `Optimizer: GPORCA` | `Optimizer: Pivotal Optimizer (GPORCA)` |

In 7.x the line is emitted at the end of `ExplainPrintPlan()`, so it sits between the last
plan node and `Planning Time:`. In 6.x it is emitted after the slice statistics, near the
bottom of the whole output. In `FORMAT JSON` / `YAML` / `XML` it is the `Optimizer`
property of the query object.

**Incorrect (assuming the GUC decided which optimizer ran):**

```sql
-- Bad: this proves nothing about which optimizer produced the plan below.
SET optimizer = on;
EXPLAIN SELECT count(DISTINCT customer_id), count(DISTINCT product_id) FROM orders;
```

**Correct (make the plan state its optimizer, and make fallbacks audible):**

```sql
-- Good: the plan names its optimizer, and the fallback reason is printed.
SET optimizer = on;
SET optimizer_trace_fallback = on;

EXPLAIN SELECT count(DISTINCT customer_id), count(DISTINCT product_id) FROM orders;
-- INFO:  GPORCA failed to produce a plan, falling back to Postgres-based planner
-- DETAIL:  Falling back to Postgres-based planner because GPORCA does not support
--          the following feature: Multiple Distinct Qualified Aggregates are
--          disabled in the optimizer
--  ...
--  Optimizer: Postgres-based planner
```

To check the setting itself rather than a plan, `SHOW optimizer;` reports the request and
the `Optimizer:` line reports the outcome. When they disagree, the query hit a fallback —
see `opt-detect-silent-orca-fallback` for the catalogue of reasons.

Reference: [Overview of the EXPLAIN SQL command](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/explain.html)
