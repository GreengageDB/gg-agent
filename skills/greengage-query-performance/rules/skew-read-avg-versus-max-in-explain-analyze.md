---
title: Read avg versus max on the slice lines as a free skew signal
impact: HIGH
impactDescription: "Every EXPLAIN ANALYZE already contains a per-segment spread; reading it costs nothing and identifies the overloaded segment by number"
tags: [query-performance, skew, explain, diagnosis]
---

## Read `avg` versus `max` on the slice lines as a free skew signal

**Impact: HIGH**

The per-slice summary at the bottom of every `EXPLAIN ANALYZE` already reports the spread
across segments, and names the worst one. `src/backend/commands/explain_gp.c` formats it
as:

```
   (slice0)    Executor memory: 156K bytes.
 * (slice1)    Executor memory: 94K bytes avg x 3 workers, 100K bytes max (seg1).  Work_mem: 65K bytes max, 1K bytes wanted.
   (slice2)    Executor memory: 151K bytes.
```

Read three things from those lines. `avg x N workers` versus `max (segN)` is the memory
spread — a max more than about 1.5x the average means one segment is doing
disproportionate work, and `segN` names it. The leading `*` is set by the code exactly when
that slice wanted more work memory than it had, so it marks the spilling slice without you
parsing anything. A slice line with no `avg x N workers` at all is a coordinator-only or
single-segment slice.

Node lines carry the same shape when they allocate their own memory context:
`Executor Memory: 76kB  Segments: 3  Max: 26kB (segment 2)`. With
`EXPLAIN (ANALYZE, VERBOSE)` you additionally get
`work_mem: NkB  Segments: N  Max: NkB (segment N)  Workfile: (N spilling)` — and
`Workfile: (1 spilling)` on a 24-segment cluster is computational skew, not a memory
shortage.

**Incorrect (reading only the totals):**

```sql
-- Bad: "Execution Time: 41s, Memory used: 128000kB, looks like it needs more
-- memory." The slice lines said one segment out of three did all the work.
EXPLAIN ANALYZE SELECT country, count(*) FROM events GROUP BY country;
```

**Correct (compare avg to max, then confirm per segment):**

```sql
-- Good: VERBOSE for the per-node work_mem/Workfile lines, allstat for the
-- full per-segment row counts of every node.
SET gp_enable_explain_allstat = on;
EXPLAIN (ANALYZE, VERBOSE) SELECT country, count(*) FROM events GROUP BY country;
RESET gp_enable_explain_allstat;
```

Two GUCs add detail when the default lines are not enough, both `USERSET`:
`explain_memory_verbosity` (default `suppress`; `summary` adds a `Vmem reserved:` figure
to each slice line, `detail` adds an `Executor Memory:` line to every executor node) and
`gp_enable_explain_allstat` (default `off`; appends
`allstat: seg_firststart_total_ntuples/seg0_.../seg1_...` per node, which is the only way
to see every segment's row count rather than the maximum).

Reference: [How to analyze and optimize SQL queries](https://greengagedb.org/en/docs-gg/current/analyze_queries.html)
