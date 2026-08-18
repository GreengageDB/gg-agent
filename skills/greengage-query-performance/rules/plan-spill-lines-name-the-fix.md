---
title: Read the workfile and memory lines before changing anything
impact: MEDIUM-HIGH
impactDescription: "Memory wanted: is a measured number that replaces every guess about statement_mem; spilling operators run at disk speed instead of memory speed"
tags: [query-performance, plan, memory, spill, workfile]
---

## Read the workfile and memory lines before changing anything

**Impact: MEDIUM-HIGH**

When a Sort, HashAggregate, Hash Join or Materialize exceeds its share of
`statement_mem`, it writes **work files** to segment-local disk and keeps going. This is
correct behaviour, not an error, and it is invisible unless you read the right lines.
`src/backend/commands/explain_gp.c` emits four of them:

| Line | Where | Meaning |
|---|---|---|
| `work_mem: NkB  Segments: N  Max: NkB (segment N)  Workfile: (N spilling)` | on the node, `EXPLAIN (ANALYZE, VERBOSE)` only | work memory summed over segments, the worst segment, and how many segments spilled here. The clause is printed on every Sort / HashJoin / hashed Agg / Material node, so `(0 spilling)` is the normal no-spill reading |
| `Work_mem wanted: <size> to lessen workfile I/O.` | on the node, VERBOSE only, and only when something wanted more | how much work memory this node needed |
| `* (sliceN)  ... Work_mem: <used> max, <wanted> wanted.` | slice summary | the `*` marks the slice that wanted more than it got |
| `Memory wanted:  NkB` | statement summary | the `statement_mem` value that would have avoided all spilling |

`Workfile:` and `Work_mem wanted:` require `VERBOSE`; the slice `*` and `Memory wanted:`
appear with plain `EXPLAIN (ANALYZE)`. `Memory used:` is printed on every `EXPLAIN ANALYZE`
(unless the memory policy is `none`) and is just the memory the statement was
**granted** — under the default resource-queue policy that is `statement_mem`, and it tells
you nothing about consumption.

**Incorrect (guessing a memory value from the shape of the query):**

```sql
-- Bad: no measurement, and this is charged on every segment for every
-- concurrent statement in this session. (Anything at or above the default
-- max_statement_mem of 2048000kB is rejected outright, so you cannot even
-- guess big.)
SET statement_mem = '1900MB';
EXPLAIN ANALYZE SELECT customer_id, count(*) FROM orders GROUP BY customer_id;
```

**Correct (measure first, then set exactly what the plan asked for):**

```sql
-- Good: VERBOSE exposes the per-node spill lines and the measured requirement.
EXPLAIN (ANALYZE, VERBOSE) SELECT customer_id, count(*) FROM orders GROUP BY customer_id;
--          Sort Method:  external merge  Disk: 41216kB  Max Memory: 20608kB  Avg Memory: 13736kB (3 segments)
--          work_mem: 196608kB  Segments: 3  Max: 65536kB (segment 1)  Workfile: (3 spilling)
--          Work_mem wanted: 191488K bytes avg, 205824K bytes max (seg1) to lessen workfile I/O
--                           affecting 3 workers.
--  * (slice1)    Executor memory: ... Work_mem: 65536K bytes max, 205824K bytes wanted.
--  Memory used:  128000kB
--  Memory wanted:  412000kB

SET statement_mem = '420MB';   -- session only; see mem-raise-statement-mem-per-session-not-globally
```

`Sort Method:  external merge  Disk: NkB` is the spill indicator on a Sort node, and the
size is summed across segments; the `Workfile:` count is the one that says how many
segments spilled. Every memory figure printed by the slice and `Work_mem wanted:` lines is
formatted as `%.0fK bytes` (`cdbexplain_formatMemory()`) — there is no `M bytes` or
`G bytes` form, so a large spill shows up as a six- or seven-digit `K bytes` number.
`Workfile: (1 spilling)` on a 24-segment cluster is skew, not a memory
shortage — see `skew-computational-skew-is-not-data-skew`. Note the `Max Memory` /
`Avg Memory` labels on that line are hardcoded and appear even when the space type is
`Disk`; they do not mean the sort stayed in memory.

Reference: [How to manage spill files](https://greengagedb.org/en/docs-gg/current/spill_files.html)
