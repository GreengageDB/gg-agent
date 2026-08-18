---
title: Measure data skew by counting rows per gp_segment_id
impact: CRITICAL
impactDescription: "A query finishes when its slowest segment finishes; a table with 5x skew runs 5x slow regardless of plan quality, and no plan change recovers it"
tags: [query-performance, skew, distribution, diagnosis]
---

## Measure data skew by counting rows per `gp_segment_id`

**Impact: CRITICAL**

Every table has a hidden `gp_segment_id` system column holding the content id of the
segment the row lives on. Grouping by it is the ground truth for data skew: no view, no
estimate, no sampling. Do this before you read a plan, because a skewed table makes every
other measurement misleading — the `max` in every `EXPLAIN ANALYZE` line, the wall-clock
time, the memory numbers all come from the overloaded segment.

The cluster runs at the speed of its worst segment. With 24 segments and one holding 20%
of the rows, that segment does 4.8x its share of the scanning, hashing and aggregating
while 23 others idle. The documentation's threshold is explicit: "Tables that have more
than 10% skew should have their distribution policies evaluated."

**Incorrect (inferring skew from the plan):**

```sql
-- Bad: "actual rows=4,200,000 but the estimate was 1,000,000, so 4x skew."
-- The actual count is the busiest segment's, and the estimate is a per-segment
-- estimate. This ratio says nothing about distribution at all.
EXPLAIN ANALYZE SELECT count(*) FROM events;
```

**Correct (count rows per segment, including the empty ones):**

```sql
-- Good: a right join against the primary segment list so segments holding
-- zero rows still appear - those are the ones doing no work at all.
SELECT s.content            AS segment,
       coalesce(e.cnt, 0)   AS rows_on_segment
FROM   gp_segment_configuration s
LEFT   JOIN (SELECT gp_segment_id, count(*) AS cnt
             FROM   events
             GROUP  BY gp_segment_id) e
       ON e.gp_segment_id = s.content
WHERE  s.role = 'p' AND s.content >= 0
ORDER  BY rows_on_segment DESC;
```

Reduce that to a single number when you are checking many tables:

```sql
SELECT round(100.0 * stddev(cnt) / nullif(avg(cnt), 0), 1) AS skew_pct
FROM  (SELECT gp_segment_id, count(*) AS cnt
       FROM   events GROUP BY gp_segment_id) s;
```

That expression is the same coefficient of variation
`gp_toolkit.gp_skew_coefficients.skccoeff` reports (`stddev(segtupcount)/avg(segtupcount)
* 100`), computed for one table instead of all of them — see
`skew-toolkit-views-scan-every-table` for why that matters. One difference to keep in mind:
`gp_skew_details()` emits a row per segment including the empty ones, so if any segment
holds zero rows, use the `gp_segment_configuration` join above as the input instead of the
bare `GROUP BY gp_segment_id`, or the two numbers will not agree.

Two cases where this query is not the right tool. On a `DISTRIBUTED REPLICATED` table
`gp_segment_id` is not exposed at all and the query fails; the documentation states it
outright: "A query that references the `gp_segment_id` system column on a replicated table
fails because Greengage DB does not allow queries to reference replicated tables' system
columns." That is correct, since every segment holds a full copy. And on a large
append-optimized table, prefer the metadata path — it reads `pg_aoseg` instead of scanning
every row, needs only `SELECT` privilege, and raises
`ERROR: '<name>' is not an append-only relation` on a heap table:

```sql
SELECT segmentid, tupcount FROM pg_catalog.get_ao_distribution('events'::regclass);
```

The fix for real data skew is a different distribution key, which is a schema change — see
the `greengage-schema-design` skill.

Reference: [Distribution in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/current/table_distribution.html)
