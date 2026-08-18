---
title: Measure skew on real data before you trust a distribution key
impact: HIGH
impactDescription: "Cardinality estimates lie about real-world value frequency; a key that looks unique in the model can still put 40% of the rows on one segment"
tags: [schema, distribution, skew, gp_toolkit, verification]
---

## Measure skew on real data before you trust a distribution key

**Impact: HIGH**

A distribution key that is theoretically high-cardinality can still be badly skewed in
practice: a `customer_id` where one house account holds a third of the orders, a
`device_id` where a test rig emitted a billion rows, a nullable column that turned out to
be 60% NULL in production. Skew is a property of the data, not of the schema, so it can
only be found by measuring it — after a representative load, and again after the data
grows.

Two things to measure, and they are different:

- **Data skew** — how unevenly rows sit on segments. Count by `gp_segment_id`, or use
  `gp_toolkit.gp_skew_coefficients` (columns `skcoid`, `skcnamespace`, `skcrelname`,
  `skccoeff`; higher coefficient = more skew).
- **Processing skew** — how unevenly a *query* loads the segments, which a redistribute on
  a skewed join key causes even when the tables themselves are even.
  `gp_toolkit.gp_skew_idle_fractions` (`sifoid`, `sifnamespace`, `sifrelname`,
  `siffraction`) reports the fraction of segment time spent idle during a scan.

The documented threshold: "tables that have more than 10% skew should have their
distribution policies evaluated".

**Incorrect (declaring victory from the DDL):**

```sql
-- Bad: "customer_id has millions of distinct values, so it must be even"
CREATE TABLE orders (order_id bigint, customer_id bigint, total numeric(12,2))
DISTRIBUTED BY (customer_id);
```

**Correct (load, then measure the actual per-segment row counts):**

```sql
-- Good: exact row counts per segment; the hidden gp_segment_id column is the ground truth
SELECT gp_segment_id,
       count(*) AS rows,
       round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct
FROM   orders
GROUP  BY gp_segment_id
ORDER  BY rows DESC;
```

An even table shows every segment within a few percent of `100 / N`. One segment far above
the rest means the key is skewed; several segments at zero means cardinality is below the
segment count.

`gp_toolkit` is an installed extension on 7.x (`CREATE EXTENSION gp_toolkit`,
`gpcontrib/gp_toolkit`) and is loaded by `initdb` on 6.x, so the views exist on both lines:

```sql
SELECT skcnamespace, skcrelname, skccoeff
FROM   gp_toolkit.gp_skew_coefficients
ORDER  BY skccoeff DESC
LIMIT  20;
```

Note that `gp_segment_id` is not exposed on `DISTRIBUTED REPLICATED` tables — by
construction every segment holds every row, so there is nothing to measure.

Reference: [Greengage DB system view: gp_skew_coefficients](https://greengagedb.org/en/docs-gg/current/reference/gp_toolkit/gp_skew_coefficients.html)
