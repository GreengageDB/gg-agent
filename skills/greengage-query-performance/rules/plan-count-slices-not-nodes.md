---
title: Count slices and gangs, not plan nodes
impact: HIGH
impactDescription: "Each segment-gang slice costs one process per segment for the life of the query; a plan with five such slices on a 24-segment cluster starts 120 backends, which is a concurrency limit, not a detail"
tags: [query-performance, plan, slices, gangs]
---

## Count slices and gangs, not plan nodes

**Impact: HIGH**

Greengage cuts the plan tree into **slices** at every `Motion` node, and dispatches each
slice to a **gang** — one process per segment, all started before the query runs and all
alive until it finishes. The slice number is printed on the Motion line itself:
`Gather Motion 3:1  (slice1; segments: 3)` means slice 1 runs on 3 segments and feeds
slice 0 on the coordinator. `src/backend/commands/explain.c` (`show_dispatch_info()`)
prints `(sliceN)` with no segment count when the slice runs only on the coordinator or an
entry-db reader.

Process count is the **sum of the gang sizes**, and it is charged per **concurrent query**.
Slice 0 is the coordinator and has gang size 0; a `Singleton Reader` slice has gang size 1;
every other slice has one process per segment. So a six-slice plan whose slices 1-5 all run
on all segments occupies 5 x 24 = 120 segment backends plus the coordinator on a
24-segment cluster; run twenty of those at once and you are at the connection limit
regardless of how fast each individual query is. Reducing motions therefore reduces
concurrency pressure as well as network traffic.

7.x adds an `EXPLAIN` option that prints the slice table directly, including the gang type
of each slice — this does not exist on 6.x:

```
Slice 0: Dispatcher; root 0; parent -1; gang size 0
Slice 1: Reader; root 0; parent 0; gang size 3
Slice 2: Reader; root 0; parent 1; gang size 3
Slice 3: Primary Writer; root 0; parent 1; gang size 3
Slice 4: Singleton Reader; root 0; parent 3; gang size 1; segment 1
```

Gang types are `Dispatcher` (coordinator only), `Entry DB Reader`, `Singleton Reader`
(exactly one segment), `Reader` (all segments, read-only) and `Primary Writer` (all
segments, holds the write locks). A plan with a `Primary Writer` gang is doing DML even if
the SQL looks like a `SELECT` — a data-modifying CTE, for instance.

**Incorrect (judging plan complexity by node count):**

```sql
-- Bad: "only nine nodes, this plan is simple" - it is five slices deep.
EXPLAIN (COSTS OFF)
WITH cte AS (INSERT INTO with_test VALUES (1, 2) RETURNING *)
SELECT i FROM cte a JOIN cte b USING (i);
```

**Correct (ask for the slice table and count gangs):**

```sql
-- Good: 7.x prints one line per slice, with its gang type and gang size.
EXPLAIN (SLICETABLE, COSTS OFF)
WITH cte AS (INSERT INTO with_test VALUES (1, 2) RETURNING *)
SELECT i FROM cte a JOIN cte b USING (i);
```

On 6.x, count the distinct `sliceN` labels in the plan text instead — there is no
`SLICETABLE` option. In `EXPLAIN ANALYZE` on both lines, the per-slice summary at the
bottom (`  (slice1)    Executor memory: ...`) has exactly one line per slice, which is the
easiest slice count you will get.

Reference: [How to analyze and optimize SQL queries](https://greengagedb.org/en/docs-gg/current/analyze_queries.html)
