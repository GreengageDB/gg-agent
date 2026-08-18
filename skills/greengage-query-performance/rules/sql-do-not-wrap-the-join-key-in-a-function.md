---
title: Never cast or wrap the distribution key in a join predicate
impact: MEDIUM-HIGH
impactDescription: "A cast on the join key destroys co-location even when both tables are distributed on it, reintroducing a full Redistribute Motion that was already paid for at design time"
tags: [query-performance, sql, join, motion, distribution]
---

## Never cast or wrap the distribution key in a join predicate

**Impact: MEDIUM-HIGH**

Co-location is a property of the **hash value**, not of the column name. Rows land on
`hash(distribution_key) mod N`, and the optimizer can skip the Motion only when it can
prove both sides of the equality hash the same way. `f(a) = f(b)` proves nothing about
`hash(a)` versus `hash(b)`, so any cast, function call or expression on either side of the
join predicate forces a `Redistribute Motion` — on tables that were deliberately
distributed to avoid exactly that.

The same rule applies to type mismatch without an explicit cast. If `orders.customer_id`
is `bigint` and `customers.customer_id` is `numeric`, the parser inserts an implicit cast
on one side, and it costs the same Motion as if you had written it yourself. Type
alignment between join columns is therefore a distribution decision.

**Incorrect (an explicit cast that throws away co-location):**

```sql
-- Bad: both tables are DISTRIBUTED BY (customer_id), but the cast means the
-- optimizer cannot match hash values and inserts a Redistribute Motion.
EXPLAIN (COSTS OFF)
SELECT c.region, count(*)
FROM   orders o
JOIN   customers c ON o.customer_id::text = c.customer_id::text
GROUP  BY c.region;
--          ->  Redistribute Motion 3:3  (slice2; segments: 3)
--                Hash Key: ((o.customer_id)::text)
```

**Correct (join the bare columns):**

```sql
-- Good: bare columns of the same type, so the join stays local.
EXPLAIN (COSTS OFF)
SELECT c.region, count(*)
FROM   orders o
JOIN   customers c ON o.customer_id = c.customer_id
GROUP  BY c.region;
```

If the two columns genuinely have different types, fix the type rather than the query —
casting is a per-execution cost that a one-time `ALTER TABLE` removes. Check for the
mismatch directly:

```sql
SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod) AS type
FROM   pg_class c
JOIN   pg_attribute a ON a.attrelid = c.oid
WHERE  c.relname IN ('orders', 'customers') AND a.attname = 'customer_id';
```

Filters are the friendlier case: a cast in a `WHERE` clause does not cost a Motion, but it
does defeat index and partition elimination — see
`sql-keep-partition-predicates-on-the-bare-key`.

Reference: [Distribution in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/current/table_distribution.html)
