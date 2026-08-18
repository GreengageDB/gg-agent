---
title: Read rows= below a Motion as the busiest segment, not the total
impact: CRITICAL
impactDescription: "Reading the per-segment maximum as a cluster total makes every estimate look wrong by a factor of N and sends the investigation to the planner instead of to the data"
tags: [query-performance, plan, explain, skew]
---

## Read `rows=` below a Motion as the busiest segment, not the total

**Impact: CRITICAL**

In `EXPLAIN ANALYZE`, the coordinator collects one statistics record per segment process
for every plan node, then copies the record of the segment that produced the **most rows**
into the node it prints. `src/backend/commands/explain_gp.c` does this explicitly:

```c
instr->ntuples = ntuples.nsimax->ntuples;   /* nsimax = the segment with max rows */
```

So `(actual rows=1200 loops=1)` on a `Seq Scan` below a `Gather Motion 24:1` means *one*
segment scanned 1200 rows. If the data is even, the cluster scanned roughly 24 x 1200. If
the data is skewed, it scanned somewhere between 1200 and 24 x 1200 — and that ambiguity
is exactly the signal. The estimated `rows=` on the same line is also a per-segment
estimate, which is why estimate and actual are directly comparable even though neither is
a cluster total.

Above the `Gather Motion` the numbers become totals again, because there is only one
process. That is the boundary to watch: a `Gather Motion` node showing `rows=28800` above
a `Seq Scan` showing `rows=1200` is not a 24x planner error, it is 24 segments.

**Incorrect (treating the node count as a cluster total):**

```sql
-- Bad reading: "the planner thought 1000 rows and got 1200, close enough,
-- but the Gather says 28800 so something is badly wrong."
EXPLAIN (ANALYZE, COSTS OFF) SELECT * FROM events WHERE event_day = DATE '2024-06-01';
--  Gather Motion 24:1  (slice1; segments: 24) (actual rows=28800 loops=1)
--    ->  Seq Scan on events (actual rows=1200 loops=1)
```

**Correct (verify the total, and the spread, with a real query):**

```sql
-- Good: ask the cluster for the true total and the per-segment spread.
SELECT sum(cnt)                        AS total_rows,
       round(avg(cnt))                 AS avg_per_segment,
       max(cnt)                        AS max_per_segment,
       round(max(cnt) / avg(cnt), 2)   AS max_over_avg
FROM  (SELECT gp_segment_id, count(*) AS cnt
       FROM   events
       WHERE  event_day = DATE '2024-06-01'
       GROUP  BY gp_segment_id) s;
```

To see every segment's row count for a node instead of just the maximum, turn on the
all-segment dump. It appends one line per node listing `seg<id>_<firststart>_<total>_<rows>`:

```sql
SET gp_enable_explain_allstat = on;
EXPLAIN (ANALYZE, COSTS OFF) SELECT * FROM events WHERE event_day = DATE '2024-06-01';
-- allstat: seg_firststart_total_ntuples/seg0_.../seg1_.../seg2_...
RESET gp_enable_explain_allstat;
```

Reference: [How to analyze and optimize SQL queries](https://greengagedb.org/en/docs-gg/current/analyze_queries.html)
