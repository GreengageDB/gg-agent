---
title: Run ANALYZE explicitly after every load - nothing does it for you
impact: HIGH
impactDescription: "gp_autostats_mode defaults to none, so a freshly loaded table has the statistics of an empty table and both optimizers will broadcast it"
tags: [query-performance, statistics, analyze, loading]
---

## Run `ANALYZE` explicitly after every load - nothing does it for you

**Impact: HIGH**

`gp_autostats_mode` defaults to `none` in `src/backend/utils/misc/guc_gp.c`, and nothing in
the shipped `postgresql.conf` overrides it. `CREATE TABLE AS`, `INSERT ... SELECT`, `COPY`,
`gpfdist` loads and external-table reads therefore leave `pg_statistic` untouched.
Autovacuum does not cover for it either: on 6.x `src/backend/postmaster/autovacuum.c` says
"In GPDB, autovacuum is currently disabled, except for the anti-wraparound vacuum of
template0 ... The administrator is expected to do all VACUUMing manually", and on 7.x
`gp_autovacuum_scope` defaults to `catalog`.

A table with no statistics looks tiny to both optimizers, and the cheapest plan for a tiny
table is a `Broadcast Motion` — send all of it to every segment. Load a billion rows, skip
`ANALYZE`, and the next join broadcasts a billion rows N times.

The autostats modes, if you want the database to do it (all are `USERSET`):

| `gp_autostats_mode` | Behaviour | Lines |
|---|---|---|
| `none` | never collect automatically | **default**, 6.x and 7.x |
| `on_no_stats` | analyze after `CREATE TABLE AS` / `INSERT` if the table has no stats at all | both |
| `on_change` | analyze when rows added exceed `gp_autostats_on_change_threshold` (default `INT_MAX`, i.e. never — you must lower it) | both |
| `on_change_and_no_stats` | both of the above | **6.x only** |

`gp_autostats_mode_in_functions` is the separate setting for statements inside PL/pgSQL
functions; it also defaults to `none`.

**Incorrect (a load that leaves the planner blind):**

```sql
-- Bad: 400M rows, zero statistics, and the next query that joins this table
-- will plan it as if it were empty.
CREATE TABLE orders_2024 (LIKE orders INCLUDING ALL) DISTRIBUTED BY (customer_id);
INSERT INTO orders_2024 SELECT * FROM orders_stage WHERE ordered_at >= DATE '2024-01-01';
```

**Correct (analyze as the last step of the load, in the same script):**

```sql
-- Good: ANALYZE is part of the load, not an afterthought.
CREATE TABLE orders_2024 (LIKE orders INCLUDING ALL) DISTRIBUTED BY (customer_id);
INSERT INTO orders_2024 SELECT * FROM orders_stage WHERE ordered_at >= DATE '2024-01-01';
ANALYZE orders_2024;
```

Verify rather than assume — `pg_stats` has one row per analyzed column, and
`pg_class.reltuples` / `relpages` stay at `0` for a relation that has never been analyzed
or vacuumed:

```sql
SELECT relname, reltuples, relpages
FROM   pg_class WHERE relname = 'orders_2024';

SELECT count(*) AS analyzed_columns
FROM   pg_stats WHERE schemaname = 'public' AND tablename = 'orders_2024';
```

For a whole database after a bulk load, `analyzedb` parallelises the work — but read
`stats-analyzedb-is-incremental-only-for-append-optimized` first, because its incremental
behaviour is narrower than the name suggests.

Reference: [How to collect statistics via ANALYZE](https://greengagedb.org/en/docs-gg/current/statistics_analyze.html)
