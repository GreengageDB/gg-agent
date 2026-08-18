---
title: Distribute on a high-cardinality, low-NULL column
impact: CRITICAL
impactDescription: "A key with fewer distinct values than segments leaves segments idle; the cluster then runs at the speed of its busiest segment, not the sum of all of them"
tags: [schema, distribution, skew]
---

## Distribute on a high-cardinality, low-NULL column

**Impact: CRITICAL**

Every row is hashed on the distribution key and the 32-bit hash is reduced to one segment
number — by jump-consistent hashing for the default hashops, by bitmask or modulo for the
legacy ones (`cdbhashreduce()`, `src/backend/cdb/cdbhash.c`). Whatever the reduction,
equal key values always land on the same segment, so distinct-value count is a hard
ceiling on parallelism: a key with 3 distinct values can occupy at most 3 segments, and
the other N-3 hold nothing and contribute nothing to any scan, aggregate or join over that
table. NULLs are worse than a low-cardinality value: `cdbhash()` skips the hash function
entirely for a NULL datum, so every row with a NULL key hashes identically and a nullable
key concentrates the entire NULL population onto one segment.

The documentation's threshold is explicit: "tables that have more than 10% skew should
have their distribution policies evaluated". A composite key (`DISTRIBUTED BY (a, b)`)
raises cardinality but only co-locates joins that equate **both** columns, so add columns
only when you need the cardinality, not by reflex.

**Incorrect (low-cardinality and nullable key):**

```sql
-- Bad: ~6 distinct statuses plus NULL -> at most 7 of N segments hold data
CREATE TABLE orders (
    order_id     bigint  NOT NULL,
    customer_id  bigint  NOT NULL,
    order_status text,            -- 'new','paid','shipped','cancelled',...
    ordered_at   timestamptz,
    total        numeric(12,2)
)
DISTRIBUTED BY (order_status);
```

**Correct (unique, NOT NULL key):**

```sql
-- Good: order_id is unique and NOT NULL, so every segment gets ~1/N of the rows
CREATE TABLE orders (
    order_id     bigint  NOT NULL,
    customer_id  bigint  NOT NULL,
    order_status text,
    ordered_at   timestamptz,
    total        numeric(12,2)
)
DISTRIBUTED BY (order_id);
```

Check a candidate column before you commit to it — this runs on the source table and needs
no schema change:

```sql
SELECT count(*)                                        AS rows,
       count(DISTINCT order_status)                    AS distinct_vals,
       count(*) FILTER (WHERE order_status IS NULL)    AS nulls
FROM   orders;
```

Reference: [Distribution in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/current/table_distribution.html)
