---
title: Name the spilling session with the gp_workfile views before killing anything
impact: MEDIUM
impactDescription: "gp_workfile_usage_per_query joins live work-file usage to pg_stat_activity, so a full segment disk becomes a named session and query text in one query"
tags: [query-performance, memory, spill, gp-toolkit, diagnosis]
---

## Name the spilling session with the `gp_workfile` views before killing anything

**Impact: MEDIUM**

`gp_toolkit` exposes what is on segment disk **right now**, joined to `pg_stat_activity`,
so "a segment's filesystem is filling up" becomes "session 4412 running this SQL is using
80 GB on segment 7" without logging in to a host.

| View | Grain | Columns |
|---|---|---|
| `gp_toolkit.gp_workfile_entries` | one row per work-file set per segment | `datname, pid, sess_id, command_cnt, usename, query, segid, slice, optype, size, numfiles, prefix` |
| `gp_toolkit.gp_workfile_usage_per_query` | one row per query per segment | the same, with `size` and `numfiles` summed |
| `gp_toolkit.gp_workfile_usage_per_segment` | one row per primary segment | `segid, size, numfiles` |
| `gp_toolkit.gp_workfile_mgr_used_diskspace` | one row per segment, from the manager's counter | `segid, bytes` |

`optype` on `gp_workfile_entries` is the `operator_name` the code passed to
`workfile_mgr_create_set()`, not the plan node name. On 7.x the values you will actually
see are `HashJoin` (`nodeHashjoin.c`), `LogicalTape` (every Sort **and** every spilling
HashAgg, via `logtape.c`), `SharedTupleStore` and `slice<N>_tuplestore` (Material and
other tuplestores). On 6.x they are `Sort`, `HashAggregate`, `HashJoin` and `SharedSort`.
`slice` names the plan slice, so you can match an entry back to the `EXPLAIN` output
without re-running anything.

**Incorrect (killing the longest-running session and hoping):**

```sql
-- Bad: duration says nothing about disk usage. This may kill a cheap query
-- and leave the spiller running.
SELECT pg_terminate_backend(pid)
FROM   pg_stat_activity
ORDER  BY query_start LIMIT 1;
```

**Correct (find the actual consumer, then decide):**

```sql
-- Good: total work-file bytes per running query, worst first.
SELECT sess_id,
       pid,
       usename,
       pg_size_pretty(sum(size)) AS workfile_size,
       sum(numfiles)             AS files,
       count(DISTINCT segid)     AS segments,
       left(query, 120)          AS query
FROM   gp_toolkit.gp_workfile_usage_per_query
GROUP  BY sess_id, pid, usename, query
ORDER  BY sum(size) DESC
LIMIT  10;
```

```sql
-- Which segment is closest to full, and which operator is responsible.
SELECT segid, pg_size_pretty(size) AS used, numfiles
FROM   gp_toolkit.gp_workfile_usage_per_segment
ORDER  BY size DESC;

SELECT segid, slice, optype, pg_size_pretty(size) AS used, numfiles, sess_id
FROM   gp_toolkit.gp_workfile_entries
ORDER  BY size DESC
LIMIT  20;
```

A query using work files on **one** segment and not the others is computational skew, not a
memory shortage — see `skew-computational-skew-is-not-data-skew`. To stop a specific
session once you have identified it, cancel it by `pid` from `pg_stat_activity`
(`SELECT pg_cancel_backend(<pid>);`), which is gentler than terminating and releases the
work files the same way.

On 7.x these views come from the `gp_toolkit` extension (`CREATE EXTENSION gp_toolkit;` if
the schema is missing); on 6.x they are installed by `initdb` in every database. The
underlying functions are `EXECUTE ON COORDINATOR` and `EXECUTE ON ALL SEGMENTS` C
functions in `gp_workfile_mgr` (`EXECUTE ON MASTER` on 6.x), so the views read live shared
memory, not a catalog.

Reference: [Greengage DB system view: gp_workfile_usage_per_query](https://greengagedb.org/en/docs-gg/current/reference/gp_toolkit/gp_workfile_usage_per_query.html)
