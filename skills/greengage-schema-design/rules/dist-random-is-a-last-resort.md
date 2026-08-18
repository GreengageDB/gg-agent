---
title: Treat DISTRIBUTED RANDOMLY as a last resort, not a safe default
impact: MEDIUM-HIGH
impactDescription: "Random distribution guarantees even data but forbids every unique constraint and forces a motion on every join, aggregate and DISTINCT"
tags: [schema, distribution, random, constraints]
---

## Treat DISTRIBUTED RANDOMLY as a last resort, not a safe default

**Impact: MEDIUM-HIGH**

`DISTRIBUTED RANDOMLY` picks a segment for each row at random — `cdbhashrandomseg()`
(`src/backend/cdb/cdbhash.c`) is literally `random() % numsegs`, called per tuple from
`nodeMotion.c`. It is
genuinely the right answer when no column has usable cardinality and the table is never
joined — a staging landing zone, an append-only log nothing correlates against. It is the
wrong answer as a default, for two reasons the DDL does not warn you about.

**It forbids uniqueness outright.** `src/backend/cdb/cdbcat.c`
`index_check_policy_compatible()` on 7.x (`checkPolicyForUniqueIndex()` on 6.x) rejects
randomly distributed tables before it looks at any column:

| Statement | Error |
|---|---|
| `PRIMARY KEY` on a random table | `PRIMARY KEY and DISTRIBUTED RANDOMLY are incompatible` |
| `UNIQUE` on a random table | `UNIQUE and DISTRIBUTED RANDOMLY are incompatible` |
| `EXCLUDE` on a random table (7.x) | `exclusion constraint and DISTRIBUTED RANDOMLY are incompatible` |
| `SET DISTRIBUTED RANDOMLY` on a table that already has one | `cannot set to DISTRIBUTED RANDOMLY because relation has primary Key` / `... unique index`, `HINT: Drop the primary key first.` |

**Every join needs a motion.** There is no hash locus, so the planner can never prove
co-location; joins, `GROUP BY` and `DISTINCT` all get a `Redistribute Motion` or
`Broadcast Motion` first. Skew is traded for interconnect traffic on every query, forever.

**Incorrect (random to dodge a hard key choice):**

```sql
-- Bad: joined constantly to customers, but can never co-locate, and can never
--      carry the natural key as a constraint
CREATE TABLE orders (
    order_id    bigint NOT NULL,
    customer_id bigint NOT NULL,
    total       numeric(12,2)
)
DISTRIBUTED RANDOMLY;
-- ALTER TABLE orders ADD PRIMARY KEY (order_id);
-- ERROR:  PRIMARY KEY and DISTRIBUTED RANDOMLY are incompatible
```

**Correct (random only where it is actually right):**

```sql
-- Good: raw landing table, no joins, no constraints, no usable key in the payload
CREATE TABLE stg_events_raw (
    raw_line text,
    loaded_at timestamptz DEFAULT now()
)
DISTRIBUTED RANDOMLY;

-- and the modelled table it feeds keeps a real key
CREATE TABLE events (
    event_id  bigint NOT NULL,
    device_id bigint NOT NULL,
    payload   jsonb
)
DISTRIBUTED BY (event_id);
```

Note that repeating `SET DISTRIBUTED RANDOMLY` on an already-random table does nothing and
warns: `distribution policy of relation "x" already set to DISTRIBUTED RANDOMLY`,
`HINT: Use ALTER TABLE "x" SET WITH (REORGANIZE=TRUE) DISTRIBUTED RANDOMLY to force a
random redistribution.`

Reference: [Distribution in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/current/table_distribution.html)
