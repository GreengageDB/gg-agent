---
title: Use DISTRIBUTED REPLICATED for small dimension tables
impact: HIGH
impactDescription: "Replicating a small dimension removes the Broadcast Motion from every fact-dimension join, at the cost of storing and maintaining N copies of the table"
tags: [schema, distribution, replicated, dimensions, motion]
---

## Use DISTRIBUTED REPLICATED for small dimension tables

**Impact: HIGH**

A hash-distributed table can only co-locate with one join key. A star schema has many
dimensions, so most fact-dimension joins would need a `Broadcast Motion` that copies the
dimension to every segment — once per query execution. `DISTRIBUTED REPLICATED` does that
copy once, at write time: `src/backend/cdb/cdbcat.c` records `policytype = 'r'`
(`SYM_POLICYTYPE_REPLICATED`) and every primary segment stores the whole table. Joins
against it are then local no matter what the fact table is distributed on, and the planner
needs no motion at all.

It also lifts the constraint restrictions: `index_check_policy_compatible()` returns
`true` immediately for a replicated policy, so a replicated table may carry any
`PRIMARY KEY`, `UNIQUE` or `EXCLUDE` constraint, on any columns.

The price is real and scales with N:

| Cost | Detail |
|---|---|
| Storage | N full copies, N = number of primary segments |
| Write amplification | every `INSERT`/`UPDATE`/`DELETE` is applied on every segment |
| No system columns | `gp_segment_id` and `ctid` are not exposed — `src/backend/parser/parse_relation.c` hides them, because a row exists at a different `ctid` on every replica |
| No volatile defaults | `volatile expressions are not supported as default values for columns in replicated tables` — a `DEFAULT random()` would give a different value per replica |
| No inheritance | `cannot inherit from replicated table "x" to create table "y"` |

Use it for tables that are small and change rarely: currency and country codes, status
lookups, calendars, small product hierarchies. Do not use it for anything a load job
rewrites nightly at scale.

**Incorrect (small lookup hashed on its key, broadcast on every join):**

```sql
-- Bad: 200 rows, but each join to a fact table broadcasts it to every segment
CREATE TABLE dim_currency (
    currency_code text NOT NULL PRIMARY KEY,
    currency_name text    NOT NULL,
    minor_units   smallint
)
DISTRIBUTED BY (currency_code);
```

**Correct (replicated — the join is local everywhere):**

```sql
-- Good: 200 rows x N segments is nothing; every join against it is motion-free
CREATE TABLE dim_currency (
    currency_code text NOT NULL PRIMARY KEY,
    currency_name text    NOT NULL,
    minor_units   smallint
)
DISTRIBUTED REPLICATED;
```

Converting an existing table rewrites it and pushes a full copy to every segment:

```sql
ALTER TABLE dim_currency SET DISTRIBUTED REPLICATED;
```

Reference: [Distribution in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/current/table_distribution.html)
