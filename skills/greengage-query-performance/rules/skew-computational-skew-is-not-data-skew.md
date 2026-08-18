---
title: Check the join and group keys for computational skew, not just the distribution key
impact: CRITICAL
impactDescription: "Perfectly distributed data can still process on one segment: a Redistribute Motion on a skewed key concentrates the whole hash table, and the query runs single-segment"
tags: [query-performance, skew, motion, aggregation]
---

## Check the join and group keys for computational skew, not just the distribution key

**Impact: CRITICAL**

Data skew and computational skew are different failures that look identical from the
outside. **Data skew** is uneven *storage*: measured by counting rows per `gp_segment_id`,
caused by the distribution key, fixed by changing it. **Computational skew** is uneven
*processing* of evenly stored data: a `Redistribute Motion` rehashes rows on the join or
group key, and if that key is skewed the destination segments receive wildly different
amounts even though the source table was perfectly balanced.

The mechanism is direct. `GROUP BY country` on a globally-distributed events table
redistributes on `country`; if 60% of events are from one country, one segment builds 60%
of the hash table, spills while the others do not, and finishes last. The storage-skew
views report this table as perfectly even, because it is. `gp_toolkit.gp_skew_idle_fractions`
is the toolkit view aimed at this ("the percentage of the system that is idle during a
table scan, which is an indicator of computational skew"), but the cheapest test is to
count the key you are about to redistribute on.

**Incorrect (checking the distribution key when the group key is the problem):**

```sql
-- Bad: events is distributed by event_id and is perfectly even, so this
-- returns a flat result and the investigation stops. But the query below
-- redistributes on country, not event_id.
SELECT gp_segment_id, count(*) FROM events GROUP BY gp_segment_id;

SELECT country, count(*) FROM events GROUP BY country;   -- still slow
```

**Correct (count the key the plan actually redistributes on):**

```sql
-- Good: the plan says "Redistribute Motion ... Hash Key: country", so measure
-- the value distribution of country. A dominant value means one segment gets
-- that whole group.
SELECT country,
       count(*)                                        AS rows,
       round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct_of_table
FROM   events
GROUP  BY country
ORDER  BY rows DESC
LIMIT  10;
```

Confirming it in the plan takes one flag. Computational skew shows up as a large
divergence between `avg` and `max` on the slice line, and as `Workfile: (1 spilling)` when
only one segment out of N spills:

```sql
SET gp_enable_explain_allstat = on;
EXPLAIN (ANALYZE, VERBOSE) SELECT country, count(*) FROM events GROUP BY country;
-- allstat: seg_firststart_total_ntuples/seg0_..._412/seg1_..._38994210/seg2_..._987
RESET gp_enable_explain_allstat;
```

Fixes are query-level, not schema-level: pre-aggregate before the redistribute (the
planner does this itself when `gp_enable_multiphase_agg` is `on`, its default), split the
dominant value out with a `UNION ALL`, or add a second grouping column that breaks the hot
value into sub-groups. Changing the table's distribution key does not help — the
redistribute happens regardless.

Reference: [Greengage DB system view: gp_skew_idle_fractions](https://greengagedb.org/en/docs-gg/current/reference/gp_toolkit/gp_skew_idle_fractions.html)
