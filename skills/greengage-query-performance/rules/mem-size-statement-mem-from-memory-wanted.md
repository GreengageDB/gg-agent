---
title: Set statement_mem from the Memory wanted line, not from a guess
impact: MEDIUM-HIGH
impactDescription: "EXPLAIN ANALYZE already computes the exact statement_mem that would have avoided all spilling; guessing either leaves the query spilling or wastes memory on every segment"
tags: [query-performance, memory, spill, statement-mem]
---

## Set `statement_mem` from the `Memory wanted:` line, not from a guess

**Impact: MEDIUM-HIGH**

`EXPLAIN ANALYZE` prints two memory lines in the statement summary, and they mean
different things:

| Line | Source | Meaning |
|---|---|---|
| `Memory used:  128000kB` | `stmt->query_mem` | the memory the statement was **granted** — this equals `statement_mem`, and says nothing about consumption |
| `Memory wanted:  412000kB` | computed from the maximum `work_mem` any node wanted | the `statement_mem` that would have avoided **all** spilling in this statement |

`Memory wanted:` is only printed when something actually wanted more than it had, so its
presence is itself the spill signal. It is a measured number derived from the real work
each operator did, which makes every rule-of-thumb about memory sizing unnecessary for
this query.

The bounds: `statement_mem` defaults to `128000` kB (125 MB), its minimum is `1000` kB, and
it is capped by `max_statement_mem` (default `2048000` kB, `PGC_SUSET`). The cap is
enforced by a check hook (`gpvars_check_statement_mem()` in `src/backend/cdb/cdbvars.c`),
and it **rejects** rather than clamps — a value greater than *or equal to*
`max_statement_mem` fails outright:

```
ERROR:  Invalid input for statement_mem, must be less than max_statement_mem (2048000 kB)
```

**Incorrect (a round number pulled from nowhere):**

```sql
-- Bad: the biggest value the default ceiling allows, because it sounds big.
-- On 24 segments that is a 45GB promise, and the query may have needed 400MB.
SET statement_mem = '1900MB';
SELECT customer_id, count(*) FROM orders GROUP BY customer_id;
```

**Correct (measure, then set the measured value):**

```sql
-- Good: one EXPLAIN ANALYZE produces the number.
EXPLAIN ANALYZE SELECT customer_id, count(*) FROM orders GROUP BY customer_id;
--  Memory used:  128000kB
--  Memory wanted:  412000kB

SET statement_mem = '420MB';
SELECT customer_id, count(*) FROM orders GROUP BY customer_id;
RESET statement_mem;
```

Two things to check before you accept the number. If `Memory wanted:` is enormous — tens
of gigabytes for a query over a modest table — the operator is not short of memory, it is
processing a skewed key and one segment is building the whole hash table; go to
`skew-computational-skew-is-not-data-skew` instead. And if the statement still spills after
you set the value, look at `EXPLAIN (ANALYZE, VERBOSE)` for the per-node
`Work_mem wanted:` lines — `statement_mem` is divided among the operators of a slice, so a
single greedy operator may still not get what it asked for.

Under `gp_resource_manager = group`, per-statement memory is governed by the resource
group as well, and `statement_mem` alone may not be the binding constraint — see the
`greengage-workload-management` skill.

Reference: [How to manage spill files](https://greengagedb.org/en/docs-gg/current/spill_files.html)
