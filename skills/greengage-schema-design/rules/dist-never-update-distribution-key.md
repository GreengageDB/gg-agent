---
title: Never design a workflow that UPDATEs a distribution key column
impact: MEDIUM-HIGH
impactDescription: "Updating the key turns each row into a delete plus an insert routed through a Split Update and a motion; on a large batch it costs more than reloading the table"
tags: [schema, distribution, dml, split-update]
---

## Never design a workflow that UPDATEs a distribution key column

**Impact: MEDIUM-HIGH**

Changing a distribution key value changes which segment the row belongs on, so the row
cannot be updated in place. The planner inserts a **Split Update** node
(`make_splitupdate_path()` in `src/backend/cdb/cdbpath.c` on 7.x, `make_splitupdate()` in
`src/backend/cdb/cdbmutate.c` on 6.x), which splits each affected row
into a delete on the current segment and an insert routed to the new one — with a motion
in between. A `UPDATE ... SET customer_id = ...` over a million rows becomes a million
deletes, a million cross-segment inserts and a full redistribution of the update stream.

On an append-optimized table it is worse: the delete only flips a bit in the visimap, so
the old row keeps occupying disk until `VACUUM` compacts the segment file (see
`store-vacuum-after-ao-dml`).

Two related restrictions worth knowing:

- In utility mode the operation is not available at all:
  `cannot update distribution key columns in utility mode`
  (`src/backend/optimizer/util/pathnode.c` on 7.x,
  `src/backend/optimizer/plan/createplan.c` on 6.x).
- `INSERT ... ON CONFLICT DO UPDATE` is not an escape hatch: 6.x has no `ON CONFLICT`
  grammar at all, and on 7.x it is rejected on append-optimized tables —
  `INSERT ON CONFLICT is not supported for appendoptimized relations`
  (`src/backend/parser/analyze.c`).

The design fix is to pick a key that is immutable by construction: a surrogate id, a
natural key that the business never restates, or the grain of the fact.

**Incorrect (mutable business attribute as the key):**

```sql
-- Bad: account reassignments are a normal business event, and each one splits rows
CREATE TABLE orders (
    order_id    bigint NOT NULL,
    account_id  bigint NOT NULL,   -- reassigned when customers are merged
    total       numeric(12,2)
)
DISTRIBUTED BY (account_id);

UPDATE orders SET account_id = 42 WHERE account_id = 17;   -- Split Update + motion
```

**Correct (immutable key; the mutable attribute is just a column):**

```sql
-- Good: order_id never changes, so account reassignment is an in-place update
CREATE TABLE orders (
    order_id    bigint NOT NULL,
    account_id  bigint NOT NULL,
    total       numeric(12,2)
)
DISTRIBUTED BY (order_id);

UPDATE orders SET account_id = 42 WHERE account_id = 17;   -- local, no motion
```

You can see the node before you run anything:

```sql
EXPLAIN UPDATE orders SET account_id = 42 WHERE account_id = 17;
--    ->  Split
-- The node is labelled "Split" in EXPLAIN output on both 6.x and 7.x
-- (src/backend/commands/explain.c, case T_SplitUpdate). Seeing it means the
-- statement is moving rows between segments.
```

Reference: [Distribution in a Greengage DB cluster](https://greengagedb.org/en/docs-gg/current/table_distribution.html)
