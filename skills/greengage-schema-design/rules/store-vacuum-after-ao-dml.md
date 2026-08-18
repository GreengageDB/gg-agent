---
title: Plan a VACUUM for every append-optimized table that receives DELETEs or UPDATEs
impact: MEDIUM-HIGH
impactDescription: "Deleted rows in an append-optimized table keep their disk space and are still read by every scan until VACUUM compacts the segment file"
tags: [schema, storage, append-optimized, vacuum, bloat]
---

## Plan a VACUUM for every append-optimized table that receives DELETEs or UPDATEs

**Impact: MEDIUM-HIGH**

An append-optimized `DELETE` does not remove data. It sets a bit in the table's **visimap**
auxiliary relation, and the row stays in the segment file — occupying disk, and still
being read and discarded by every subsequent sequential scan. `UPDATE` is a delete plus an
append, so it costs the same and then some. Space comes back only when `VACUUM` decides to
rewrite the segment file.

The decision threshold is a GUC: `gp_appendonly_compaction_threshold`, default **10**
(percent), `src/backend/utils/misc/guc_gp.c`. A lazy `VACUUM` compacts a segment file only
when the ratio of invisible tuples in it is **strictly above** that threshold
(`AppendOnlyCompaction_ShouldCompact()`, `src/backend/access/appendonly/appendonly_compaction.c`).
So a table where each load deletes 5% and reloads it never gets compacted by routine
vacuuming, and grows forever — the server logs why:

```
LOG:  Append-only compaction skipped on relation sales_fact, segment file num 1
DETAIL:  Ratio of obsolete tuples below threshold (5.000000% vs 10%)
```

Setting the GUC to `0` **disables** compaction entirely rather than forcing it — the same
branch treats `== 0` as "skip". `VACUUM FULL` is the unconditional form: it compacts
whenever there is any obsolete data at all.

This is a schema-design concern, not just an operations one, because the design choice
that avoids it is partitioning: dropping a partition reclaims the space immediately with
no scan and no compaction (see `part-load-and-age-with-exchange-and-drop`).

**Incorrect (delete-and-reload pattern on an unpartitioned AO table):**

```sql
-- Bad: every night this rewrites a slice, and every night the table gets bigger
CREATE TABLE sales_fact (
    sale_id   bigint NOT NULL,
    sale_date date   NOT NULL,
    amount    numeric(12,2)
)
USING ao_column
DISTRIBUTED BY (sale_id);

DELETE FROM sales_fact WHERE sale_date = current_date - 1;
INSERT INTO sales_fact SELECT * FROM stg_sales;
-- disk usage grows monotonically; the deleted rows are still scanned
```

**Correct (partition by the reload grain and swap the partition):**

```sql
-- Good: yesterday's data is replaced by exchanging a partition, not by DELETE
CREATE TABLE sales_fact (
    sale_id   bigint NOT NULL,
    sale_date date   NOT NULL,
    amount    numeric(12,2)
)
USING ao_column
DISTRIBUTED BY (sale_id)
PARTITION BY RANGE (sale_date)
( START (date '2026-01-01') INCLUSIVE
  END   (date '2027-01-01') EXCLUSIVE
  EVERY (INTERVAL '1 day'),
  DEFAULT PARTITION other );

CREATE TABLE sales_fact_reload (LIKE sales_fact)
  USING ao_column DISTRIBUTED BY (sale_id);
INSERT INTO sales_fact_reload SELECT * FROM stg_sales;

ALTER TABLE sales_fact
  EXCHANGE PARTITION FOR (date '2026-08-17') WITH TABLE sales_fact_reload;
```

If the delete-and-reload pattern is unavoidable, schedule the compaction explicitly rather
than hoping the threshold is crossed:

```sql
-- Lower the bar so lightly-dirtied segment files are compacted too.
-- Do NOT set it to 0: 0 means "never compact".
SET gp_appendonly_compaction_threshold = 1;
VACUUM sales_fact;
RESET gp_appendonly_compaction_threshold;

-- Unconditional, but rewrites the whole relation under an exclusive lock:
VACUUM FULL sales_fact;
```

Reference: [How to remove expired table rows via VACUUM](https://greengagedb.org/en/docs-gg/current/vacuum.html)
