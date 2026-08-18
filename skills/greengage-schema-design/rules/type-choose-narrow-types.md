---
title: Choose the narrowest type that holds the data, and order columns from wide to narrow
impact: MEDIUM
impactDescription: "Row width multiplies across every segment and every scan; oversized types and alignment padding inflate disk, compression input and interconnect traffic on every query"
tags: [schema, types, width, alignment, compression]
---

## Choose the narrowest type that holds the data, and order columns from wide to narrow

**Impact: MEDIUM**

Everything in an MPP scan scales with row width: bytes read from disk on every segment,
bytes fed to the compressor, bytes shipped through a motion, and bytes spilled to workfiles
when a hash join does not fit in memory. `numeric` where `int` would do is not a rounding
error — `numeric` is a variable-length type with per-value overhead and no hardware
arithmetic, and it also lands in a different hash opfamily, which breaks co-location with
integer keys (see `dist-match-hash-opfamily`).

Two habits worth adopting:

- **Pick the narrowest correct type.** `smallint` for enumerated codes, `int` for
  identifiers under two billion, `bigint` for surrogate keys that will exceed it, `date`
  rather than `timestamptz` when there is no time-of-day, `numeric(p,s)` only where exact
  decimal semantics are actually required (money), `real`/`double precision` never for
  money.
- **Order columns wide-to-narrow.** Greengage inherits PostgreSQL's tuple layout, so
  fixed-width columns are aligned and gaps are padding you pay for on every row. Declaring
  `int8, int8, int4, int2, bool` wastes nothing; `bool, int8, int2, int8, int4` inserts
  padding between them. Nullable columns additionally cost a null bitmap.

Column order matters much less on `ao_column` storage, where each column is stored
separately — another reason to make the storage decision consciously.

**Incorrect (over-wide types and a padding-maximising order):**

```sql
-- Bad: numeric for an id (also blocks co-location with bigint keys),
--      timestamptz where a date suffices, bool wedged between int8s
CREATE TABLE sales_fact (
    is_return   boolean,
    sale_id     numeric(18),
    status_code integer,
    customer_id numeric(18),
    sale_ts     timestamptz,
    amount      double precision
)
DISTRIBUTED BY (sale_id);
```

**Correct (narrow types, wide-to-narrow order, exact decimal only for money):**

```sql
-- Good
CREATE TABLE sales_fact (
    sale_id     bigint        NOT NULL,
    customer_id bigint        NOT NULL,
    amount      numeric(12,2) NOT NULL,
    sale_date   date          NOT NULL,
    status_code smallint      NOT NULL,
    is_return   boolean       NOT NULL DEFAULT false
)
USING ao_column
WITH (compresstype=zstd, compresslevel=5)
DISTRIBUTED BY (sale_id);
```

Measure the result rather than guessing at it:

```sql
-- average on-disk bytes per row across the whole cluster
SELECT pg_size_pretty(pg_relation_size('sales_fact')) AS on_disk,
       pg_relation_size('sales_fact') / NULLIF(count(*), 0) AS bytes_per_row
FROM   sales_fact;
```

Reference: [Overview of the CREATE TABLE SQL command](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/create_table.html)
