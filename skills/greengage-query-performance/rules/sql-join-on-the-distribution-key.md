---
title: Join on the distribution key of both tables, or expect a Motion on every run
impact: HIGH
impactDescription: "A non-co-located join moves one or both inputs across the interconnect on every execution; a broadcast multiplies the moved volume by the segment count"
tags: [query-performance, sql, join, motion, distribution]
---

## Join on the distribution key of both tables, or expect a Motion on every run

**Impact: HIGH**

A hash join can only run locally if the matching rows are already on the same segment.
That is true exactly when both tables are distributed on the join columns, with matching
hash opclasses. Otherwise the optimizer inserts a Motion under the join, and it pays that
cost on **every execution**, forever:

- `Redistribute Motion N:N  Hash Key: <col>` — rehash one or both inputs on the join key
  and resend. Cost: one full pass of that input over the interconnect.
- `Broadcast Motion N:N` — send one whole input to every segment. Cost: that input's
  volume multiplied by the segment count. Correct for a small dimension, ruinous for a
  fact table.

Check what the tables are distributed on before reading the plan —
`pg_catalog.pg_get_table_distributedby(oid)` deparses the clause on both 6.x and 7.x, and
`\d+ <table>` prints `Distributed by: (...)` at the bottom.

**Incorrect (join key is the distribution key of neither side):**

```sql
-- Bad: orders is distributed by order_id, line_items by line_id. The join is
-- on order_id, so line_items is rehashed and resent on every execution.
CREATE TABLE orders     (order_id bigint, customer_id bigint, ordered_at date)
  DISTRIBUTED BY (order_id);
CREATE TABLE line_items (line_id bigint, order_id bigint, amount numeric)
  DISTRIBUTED BY (line_id);

EXPLAIN (COSTS OFF)
SELECT o.order_id, sum(l.amount)
FROM   orders o JOIN line_items l USING (order_id)
GROUP  BY o.order_id;
--          ->  Redistribute Motion 3:3  (slice2; segments: 3)
--                Hash Key: l.order_id
```

**Correct (both sides distributed on the join key — the Motion disappears):**

```sql
-- Good: line_items distributed by order_id co-locates the join. Only the final
-- Gather Motion remains, and it carries aggregated rows.
CREATE TABLE line_items (line_id bigint, order_id bigint, amount numeric)
  DISTRIBUTED BY (order_id);

EXPLAIN (COSTS OFF)
SELECT o.order_id, sum(l.amount)
FROM   orders o JOIN line_items l USING (order_id)
GROUP  BY o.order_id;
```

Confirm the distribution before and after:

```sql
SELECT c.relname,
       pg_catalog.pg_get_table_distributedby(c.oid) AS distribution
FROM   pg_class c
JOIN   pg_namespace n ON n.oid = c.relnamespace
WHERE  n.nspname = 'public' AND c.relname IN ('orders', 'line_items');
```

Three qualifications. A composite key (`DISTRIBUTED BY (a, b)`) co-locates only joins that
equate **both** columns. `DISTRIBUTED REPLICATED` removes the Motion for small dimensions
by keeping a full copy on every segment, at the cost of N copies of the writes.
`DISTRIBUTED RANDOMLY` can never be co-located and always costs a Motion. Changing a
distribution key rewrites and redistributes the whole table, so it belongs to schema
design, not query tuning — see the `greengage-schema-design` skill.

Reference: [Distribution in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/current/table_distribution.html)
