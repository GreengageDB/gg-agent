---
title: Wrap EXPLAIN ANALYZE of DML in an explicit transaction
impact: MEDIUM-HIGH
impactDescription: "EXPLAIN ANALYZE executes the statement on every segment; on an INSERT or UPDATE the rows are really written, distributed and committed"
tags: [query-performance, plan, explain, safety]
---

## Wrap `EXPLAIN ANALYZE` of DML in an explicit transaction

**Impact: MEDIUM-HIGH**

`EXPLAIN ANALYZE` runs the statement. `doc/src/sgml/ref/explain.sgml` states it plainly:
"Keep in mind that the statement is actually executed when the `ANALYZE` option is used.
Although `EXPLAIN` will discard any output that a `SELECT` would return, other side
effects of the statement will happen as usual." On a cluster that means the write happens
on every segment, through the same `Primary Writer` gang and the same distributed
transaction the real statement would use.

Two Greengage-specific consequences on top of the PostgreSQL one. First, an error on one
segment aborts the whole statement and you get the segment's identity in the message
rather than a plan — `ERROR: ... (seg1 127.0.1.1:7003 pid=103595)`. Second, profiling
overhead is per-segment and the coordinator has to collect one statistics record per node
per segment, so `EXPLAIN ANALYZE` on a wide plan across many segments costs measurably
more than the query alone; do not treat its `Execution Time:` as the query's real latency
when you are comparing to a production number.

**Incorrect (a "just checking the plan" statement that writes 40M rows):**

```sql
-- Bad: this inserts. On every segment. Committed.
EXPLAIN ANALYZE
INSERT INTO orders_archive SELECT * FROM orders WHERE ordered_at < DATE '2023-01-01';
```

**Correct (execute it, read the plan, throw the work away):**

```sql
-- Good: the plan and the real per-segment statistics, with no committed change.
BEGIN;
EXPLAIN ANALYZE
INSERT INTO orders_archive SELECT * FROM orders WHERE ordered_at < DATE '2023-01-01';
ROLLBACK;
```

For a plan alone, with no execution and no side effects, drop `ANALYZE`. `EXPLAIN` on its
own never runs the statement, and it still shows every Motion, every slice number and the
`Optimizer:` line — which is enough for steps 2 and 3 of the diagnostic procedure:

```sql
EXPLAIN (COSTS OFF)
INSERT INTO orders_archive SELECT * FROM orders WHERE ordered_at < DATE '2023-01-01';
```

Reference: [Overview of the EXPLAIN SQL command](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/explain.html)
