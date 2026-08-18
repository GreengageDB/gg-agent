---
title: Keep row-at-a-time DML off append-optimized tables
impact: HIGH
impactDescription: "Append-optimized DELETE and UPDATE only mark rows invisible; space is reclaimed by VACUUM, and triggers, CLUSTER and concurrency behave differently from heap"
tags: [schema, storage, append-optimized, dml, vacuum]
---

## Keep row-at-a-time DML off append-optimized tables

**Impact: HIGH**

Append-optimized tables are designed for bulk load and read. `UPDATE` and `DELETE` are
allowed, but they never modify the data file: the row is marked invisible in the
**visimap** auxiliary relation (relkind `'M'`, `pg_aovisimap*`), and the space is only
reclaimed when `VACUUM` decides the segment file is dirty enough to rewrite. An
OLTP-shaped workload therefore grows the table monotonically until a maintenance window
compacts it.

Several heap behaviours are simply missing:

| Behaviour | On append-optimized tables |
|---|---|
| `ON UPDATE` / `ON DELETE` triggers | `ERROR: ON UPDATE triggers are not supported on append-only tables` (both lines, `src/backend/commands/trigger.c`) |
| `CLUSTER` | Rejected on both lines: `ERROR: cannot cluster append-optimized table "x"` on 7.x (`src/backend/access/aocs/aocsam_handler.c`), `ERROR: cannot cluster append-only table "x": not supported` on 6.x (`src/backend/commands/cluster.c`) |
| `UNIQUE` / `PRIMARY KEY` | Not supported at all on 6.x: `ERROR: append-only tables do not support unique indexes`. Supported on 7.x, but not `CONCURRENTLY`, and the relation must be at AO version GP7 |
| Concurrent writers | Bounded by `MAX_AOREL_CONCURRENCY` = 128 segment files per relation (`src/include/access/appendonlywriter.h`) |

The 7.x unique-index restriction has a specific escape hatch in the error text — a table
upgraded from 6.x carries the older relation version:

```
ERROR:  append-only tables with older relation versions do not support unique indexes
HINT:  ALTER TABLE <table-name> SET WITH (REORGANIZE = true) before creating the unique index
```

**Incorrect (transactional table stored append-optimized):**

```sql
-- Bad: rows are updated individually all day; every update leaves a dead row behind
CREATE TABLE user_sessions (
    session_id   bigint NOT NULL,
    user_id      bigint NOT NULL,
    last_seen_at timestamptz,
    state        text
)
USING ao_row
DISTRIBUTED BY (session_id);

UPDATE user_sessions SET last_seen_at = now() WHERE session_id = 12345;
```

**Correct (heap for the mutable table, append-optimized for the history it feeds):**

```sql
-- Good: the hot mutable table stays heap and supports a primary key on both lines
CREATE TABLE user_sessions (
    session_id   bigint NOT NULL PRIMARY KEY,
    user_id      bigint NOT NULL,
    last_seen_at timestamptz,
    state        text
)
DISTRIBUTED BY (session_id);

-- and the append-only history is written once, never updated
CREATE TABLE user_session_history (
    session_id   bigint NOT NULL,
    user_id      bigint NOT NULL,
    observed_at  timestamptz NOT NULL,
    state        text
)
USING ao_column
WITH (compresstype=zstd, compresslevel=5)
DISTRIBUTED BY (session_id);
```

Reference: [Table storage types in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/current/table_types.html)
