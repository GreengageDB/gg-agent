---
title: Turn on optimizer_trace_fallback before concluding anything about GPORCA
impact: HIGH
impactDescription: "GPORCA fallback is silent by default, so a session that appears to test GPORCA may have used the Postgres planner for every query in it"
tags: [query-performance, optimizer, gporca, fallback]
---

## Turn on `optimizer_trace_fallback` before concluding anything about GPORCA

**Impact: HIGH**

When GPORCA cannot translate a query, `src/backend/gpopt/CGPOptimizer.cpp` catches the
exception, returns no plan, and lets the Postgres planner produce one instead. The
explanatory message is emitted only `if (optimizer_trace_fallback)`, and that GUC defaults
to `false`. So with `optimizer = on` a query may still be planned by the Postgres planner,
and nothing in the session says so unless you asked.

With the GUC on (it is `USERSET`, so `SET` is enough) you get an `INFO` and a `DETAIL`
naming the exact unsupported feature:

```
INFO:  GPORCA failed to produce a plan, falling back to Postgres-based planner
DETAIL:  Falling back to Postgres-based planner because GPORCA does not support the
         following feature: Multiple Distinct Qualified Aggregates are disabled in the
         optimizer
```

On 6.x the first line reads `GPORCA failed to produce a plan, falling back to planner`.
Common `DETAIL` features from `src/backend/gpopt/translate/CTranslatorQueryToDXL.cpp`,
each of which sends the whole query to the Postgres planner:

| Feature named in DETAIL | Triggered by |
|---|---|
| `Multiple Distinct Qualified Aggregates are disabled in the optimizer` | two or more `DISTINCT` aggregates over **different** arguments in one query — aggregates with equal argument lists are folded by `IsDuplicateDqaArg()` and count once (`optimizer_enable_multiple_distinct_aggs` is `false` by default) |
| `LATERAL` | a `LATERAL` join |
| `WITH RECURSIVE` | a recursive CTE |
| `ON CONFLICT clause` | `INSERT ... ON CONFLICT` |
| `RETURNING clause` | DML with `RETURNING` |
| `TABLESAMPLE in the FROM clause` | `TABLESAMPLE` |
| `ONLY in the FROM clause` | `FROM ONLY parent` on an inheritance hierarchy |
| `Non-default collation` | a column or expression with a non-default collation |
| `WITH ORDINALITY` | set-returning function with `WITH ORDINALITY` |
| `UPDATE with constraints` / `INSERT with constraints` | DML against a table with `CHECK` or `NOT NULL` constraints, but **only** when `optimizer_enable_dml_constraints` has been turned off — it defaults to `true`, so this does not fire out of the box |

Two other fallback shapes come from GPORCA's own optimization phase rather than
translation, and carry no feature name:
`Falling back to Postgres-based planner because no plan has been computed for required
properties in GPORCA` and `... because plan does not satisfy required properties in
GPORCA`.

**Incorrect (benchmarking "GPORCA" without checking it ran):**

```sql
-- Bad: three of these five queries silently used the Postgres planner.
SET optimizer = on;
\timing on
SELECT count(DISTINCT customer_id), count(DISTINCT product_id) FROM orders;
SELECT * FROM orders o, LATERAL (SELECT max(amount) FROM payments p
                                 WHERE p.order_id = o.order_id) m;
```

**Correct (make every fallback audible, then decide):**

```sql
-- Good: each fallback prints its reason, so you know which measurements are
-- actually GPORCA measurements.
SET optimizer = on;
SET optimizer_trace_fallback = on;
\timing on
SELECT count(DISTINCT customer_id), count(DISTINCT product_id) FROM orders;
-- INFO:  GPORCA failed to produce a plan, falling back to Postgres-based planner
-- DETAIL:  ... Multiple Distinct Qualified Aggregates are disabled in the optimizer
RESET optimizer_trace_fallback;
```

A fallback is not an error and needs no fix by itself — the query still runs. It matters
because it invalidates any conclusion you were about to draw about GPORCA, and because the
named feature is often removable from the SQL (see `sql-count-distinct-costs-a-redistribute`).

Reference: [Server configuration parameters (GUCs) overview](https://greengagedb.org/en/docs-gg/current/reference/guc_reference.html)
