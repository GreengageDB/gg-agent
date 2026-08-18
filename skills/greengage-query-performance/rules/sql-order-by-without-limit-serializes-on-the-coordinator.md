---
title: Add a LIMIT to any ORDER BY you do not need in full
impact: MEDIUM-HIGH
impactDescription: "Every ordered row crosses the interconnect into one coordinator process; with a LIMIT the sort limit is pushed below the Gather Motion and each segment sends only N rows"
tags: [query-performance, sql, sort, motion, coordinator]
---

## Add a `LIMIT` to any `ORDER BY` you do not need in full

**Impact: MEDIUM-HIGH**

A top-level `ORDER BY` produces a per-segment `Sort` under a `Gather Motion` with a
`Merge Key:` line — the segments sort their own slices in parallel and the coordinator
merges the pre-sorted streams. The sorting is parallel; the **merge is not**. Every result
row passes through a single coordinator process, over the interconnect, one at a time.
For a ten-row report that is nothing. For a hundred-million-row extract it is the whole
query, and no plan change fixes it because the ordering requires it.

With a `LIMIT`, `src/backend/optimizer/plan/planner.c` calls
`create_preliminary_limit_path()` to add a second `Limit` node *below* the `Gather Motion`
— its comment: "add a Limit node to below the Motion, as a preliminary step, so that the
QEs can stop executing early" — so each segment sorts and then discards everything past N
before sending. The interconnect carries `segments x N` rows instead of the whole table.
The pushdown is skipped when `LIMIT`/`OFFSET` contains a volatile function
(`contain_volatile_functions()`), so `LIMIT (random() * 100)::int` gathers everything.

**Incorrect (a full ordered gather for a preview):**

```sql
-- Bad: every row of events is sorted on the segments, then funnelled one
-- process wide into the coordinator, so you can look at the first screen.
EXPLAIN (COSTS OFF)
SELECT * FROM events ORDER BY event_time DESC;
--  Gather Motion 3:1  (slice1; segments: 3)
--    Merge Key: event_time
--    ->  Sort
--          Sort Key: events.event_time DESC
--          ->  Seq Scan on events
```

**Correct (bound the gather with a LIMIT):**

```sql
-- Good: a Limit node appears below the Gather Motion, so each segment sends
-- at most 100 rows instead of all of them.
EXPLAIN (COSTS OFF)
SELECT * FROM events ORDER BY event_time DESC LIMIT 100;
--  Limit
--    ->  Gather Motion 3:1  (slice1; segments: 3)
--          Merge Key: event_time
--          ->  Limit
--                ->  Sort
--                      Sort Key: events.event_time DESC
--                      ->  Seq Scan on events
```

Two related cases. An `ORDER BY` inside a subquery or CTE whose result is then aggregated
is usually redundant — remove it and the `Sort` and its `Merge Key` disappear with it. And
when you genuinely need every row ordered, do not fight the gather: write the result to a
table with `CREATE TABLE ... AS` (which keeps the work distributed) or export it from the
segments with a writable external table instead of pulling it through `psql`.

`ORDER BY` inside a window function's `OVER (PARTITION BY ... ORDER BY ...)` is a different
thing entirely — it sorts within each segment's partition and costs no gather.

Reference: [Overview of the SELECT SQL command](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/select.html)
