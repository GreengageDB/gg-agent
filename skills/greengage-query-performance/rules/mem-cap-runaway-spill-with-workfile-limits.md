---
title: Cap exploratory queries with gp_workfile_limit_per_query
impact: HIGH
impactDescription: "All three workfile limits default to unlimited, so one bad join can fill every segment's disk and take the cluster down; a session-level cap turns that into one failed query"
tags: [query-performance, memory, spill, workfile, safety]
---

## Cap exploratory queries with `gp_workfile_limit_per_query`

**Impact: HIGH**

Spilling is bounded by three GUCs, and two of them default to **no limit**:

| GUC | Default | Scope | Unit | Enforced against |
|---|---|---|---|---|
| `gp_workfile_limit_per_query` | `0` = no limit | `USERSET` | kB | one query's work files **on each segment** |
| `gp_workfile_limit_per_segment` | `0` = no limit | `POSTMASTER` | kB | all queries' work files on one segment |
| `gp_workfile_limit_files_per_query` | `100000` | `USERSET` | files | number of work files one query may open per segment |

`src/backend/utils/workfile_manager/workfile_mgr.c` enforces them by cancelling the query
at the moment the limit is crossed, with `ERRCODE_INSUFFICIENT_RESOURCES`:

| Error | Cause |
|---|---|
| `ERROR:  workfile per query size limit exceeded` | `gp_workfile_limit_per_query` |
| `ERROR:  workfile per segment size limit exceeded` | `gp_workfile_limit_per_segment` |
| `ERROR:  number of workfiles per query limit exceeded` | `gp_workfile_limit_files_per_query` |

Because `gp_workfile_limit_per_query` is `USERSET`, it is the practical safety belt: set it
in the session before running something you have not costed, and the worst case becomes a
failed query rather than a full segment filesystem. `gp_workfile_limit_per_segment` is
`POSTMASTER`, so it is a deployment decision and cannot be adjusted for one investigation.

**Incorrect (an uncapped exploratory join on a production cluster):**

```sql
-- Bad: an accidental cross join spills until the segment disks are full,
-- which affects every other query on the cluster, not just this one.
SET statement_mem = '1GB';
SELECT count(*) FROM orders o, line_items l WHERE o.ordered_at = l.shipped_at;
```

**Correct (bound the damage before running it):**

```sql
-- Good: this query may use at most 20GB of work files per segment. If it
-- needs more, it fails and nothing else is affected.
SET gp_workfile_limit_per_query = '20GB';
SELECT count(*) FROM orders o, line_items l WHERE o.ordered_at = l.shipped_at;
-- ERROR:  workfile per query size limit exceeded
RESET gp_workfile_limit_per_query;
```

Two adjuncts. `gp_workfile_compression` (default `off`, `USERSET`) compresses work files,
trading CPU for disk and for interconnect-free I/O — useful when the spill is unavoidable;
its memory overhead is bounded by `gp_workfile_compression_overhead_limit` (default
2 GB per workfile set). And `temp_spill_files_tablespaces` (both lines) puts work files on
a dedicated tablespace, so a runaway fills that filesystem instead of the data directory —
it takes precedence over `temp_tablespaces` for spill files specifically.

Reference: [How to manage spill files](https://greengagedb.org/en/docs-gg/current/spill_files.html)
