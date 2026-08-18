---
title: Compare the two optimizers by plan shape and measured time in one session
impact: HIGH
impactDescription: "Optimizer choice regularly changes a plan's join method and motion count; picking the right one for a query is often a 2-10x win and costs two EXPLAIN ANALYZE runs"
tags: [query-performance, optimizer, gporca, method]
---

## Compare the two optimizers by plan shape and measured time in one session

**Impact: HIGH**

The two optimizers make genuinely different choices, and neither is uniformly better. The
same three-table left join in `src/test/regress/expected/explain_format.out` and
`explain_format_optimizer.out` is planned as two `Hash Left Join`s by the Postgres planner
and as two `Nested Loop Left Join`s over `Index Scan`s by GPORCA — different join methods,
different memory profiles, same answer.

Rough tendencies, useful for forming a hypothesis but never a substitute for measuring:

| GPORCA (`optimizer = on`) tends to win on | The Postgres planner (`optimizer = off`) tends to win on |
|---|---|
| many-way joins (`optimizer_join_order` defaults to `exhaustive2`, up to `optimizer_join_order_threshold` = 10 children) | simple single-table and two-table queries, where its planning time is far lower |
| partitioned tables with dynamic partition elimination | queries GPORCA falls back on anyway — the fallback costs a wasted planning attempt |
| queries where a `Broadcast` versus `Redistribute` decision needs good cardinality estimates | anything with multiple `DISTINCT` aggregates, `LATERAL`, `WITH RECURSIVE` or `RETURNING` |

**Incorrect (changing the cluster default to test a hypothesis):**

```sql
-- Bad: changes every session on every segment, needs a reload, and still does
-- not tell you whether this query got faster.
\! gpconfig -c optimizer -v off && gpstop -u
```

**Correct (two measured runs in one session, costs suppressed):**

```sql
-- Good: same session, same data, same caches. Compare Execution Time,
-- the Motion list, and the join methods - never the cost numbers.
SET optimizer_trace_fallback = on;   -- so a silent fallback cannot fake a result

SET optimizer = on;
EXPLAIN (ANALYZE, COSTS OFF) SELECT c.region, sum(o.total)
  FROM orders o JOIN customers c USING (customer_id) GROUP BY c.region;

SET optimizer = off;
EXPLAIN (ANALYZE, COSTS OFF) SELECT c.region, sum(o.total)
  FROM orders o JOIN customers c USING (customer_id) GROUP BY c.region;

RESET optimizer;
RESET optimizer_trace_fallback;
```

Compare, in this order: the `Optimizer:` line (did GPORCA actually run — see
`opt-detect-silent-orca-fallback`); the Motion nodes and their types; the number of
slices; whether any node spilled; and only then `Execution Time:`. Run each twice and take
the second, so the first run's cold cache does not decide the comparison.

If one optimizer wins for a specific query, pin it for that query with `SET optimizer` in
the session or a `SET` in the calling function — not cluster-wide. See
`opt-switch-optimizers-per-session-first`.

Reference: [How to analyze and optimize SQL queries](https://greengagedb.org/en/docs-gg/current/analyze_queries.html)
