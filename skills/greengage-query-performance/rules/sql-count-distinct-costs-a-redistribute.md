---
title: Budget for a redistribute per DISTINCT aggregate, and never use two on different columns
impact: MEDIUM-HIGH
impactDescription: "One DISTINCT aggregate adds a Redistribute Motion on the distinct key; a second one over a different column drops GPORCA to the Postgres planner for the entire query"
tags: [query-performance, sql, aggregation, distinct, gporca]
---

## Budget for a redistribute per `DISTINCT` aggregate, and never use two on different columns

**Impact: MEDIUM-HIGH**

`count(DISTINCT x)` cannot be computed by summing per-segment counts — the same value may
appear on several segments. Greengage therefore plans it in stages, and the shape depends
on whether `x` is the distribution key.

Both shapes below are from `src/test/regress/expected/gp_dqa.out`, where `dqa_t1` is
distributed on `d`. When the distinct key **is** the distribution key, every duplicate is
already co-located and the plan is a plain two-stage aggregate with no extra Motion
(`count(distinct d)`):

```
 Finalize Aggregate
   ->  Gather Motion 3:1  (slice1; segments: 3)
         ->  Partial Aggregate
               ->  Seq Scan on dqa_t1
```

When it is not (`count(distinct c)`), the plan de-duplicates locally, redistributes on the
distinct key, and aggregates again — one extra full pass over the interconnect:

```
 Finalize Aggregate
   ->  Gather Motion 3:1  (slice1; segments: 3)
         ->  Partial Aggregate
               ->  HashAggregate
                     Group Key: c
                     ->  Redistribute Motion 3:3  (slice2; segments: 3)
                           Hash Key: c
                           ->  Streaming HashAggregate
                                 Group Key: c
                                 ->  Seq Scan on dqa_t1
```

A **second** distinct aggregate over a **different** argument is a different problem.
`optimizer_enable_multiple_distinct_aggs` defaults to `false`, so
`src/backend/gpopt/translate/CTranslatorQueryToDXL.cpp` raises
`Multiple Distinct Qualified Aggregates are disabled in the optimizer` and GPORCA hands the
whole query — not just the aggregate — to the Postgres planner. The resulting plan uses a
`TupleSplit` node feeding a `Streaming HashAggregate` and redistributes on every distinct
column at once (`Hash Key: d, dt, (AggExprId)`).

The count is of distinct *arguments*, not of aggregate calls: `IsDuplicateDqaArg()` folds
aggregates whose `args` are equal, so `count(DISTINCT d), sum(DISTINCT d)` is one DQA and
GPORCA plans it normally. `count(DISTINCT d), count(DISTINCT dt)` is two, and falls back.

**Incorrect (two distinct aggregates on different columns, silently falling back):**

```sql
-- Bad: GPORCA cannot plan this and the whole query goes to the Postgres
-- planner. With optimizer_trace_fallback = on you would see it say so.
SELECT count(DISTINCT customer_id), count(DISTINCT product_id)
FROM   orders;
```

**Correct (compute them separately and join the scalars):**

```sql
-- Good: each subquery has one distinct aggregate, so each can be planned by
-- GPORCA, and the two scalars are combined at the end.
SELECT c.n_customers, p.n_products
FROM  (SELECT count(DISTINCT customer_id) AS n_customers FROM orders) c,
      (SELECT count(DISTINCT product_id)  AS n_products  FROM orders) p;
```

If you genuinely need multiple distinct aggregates in one pass, enable the feature
explicitly rather than accepting a silent fallback, and measure both ways:

```sql
SET optimizer_enable_multiple_distinct_aggs = on;
EXPLAIN (ANALYZE, COSTS OFF)
SELECT count(DISTINCT customer_id), count(DISTINCT product_id) FROM orders;
RESET optimizer_enable_multiple_distinct_aggs;
```

Two related GUCs shape the Postgres-planner path, both `on` by default:
`gp_enable_agg_distinct` (two-phase aggregation for a single distinct aggregate) and
`gp_enable_agg_distinct_pruning` (three-phase aggregation plus join for distinct
aggregates). Turning either off is a diagnostic, not a fix.

Reference: [How to analyze and optimize SQL queries](https://greengagedb.org/en/docs-gg/current/analyze_queries.html)
