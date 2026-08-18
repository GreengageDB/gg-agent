---
title: Do not tune with enable_* GUCs while GPORCA is the optimizer
impact: MEDIUM
impactDescription: "The PostgreSQL enable_* family is not mapped into GPORCA at all, so setting them under the default optimizer changes nothing and hides the real cause"
tags: [query-performance, optimizer, gporca, guc]
---

## Do not tune with `enable_*` GUCs while GPORCA is the optimizer

**Impact: MEDIUM**

`src/backend/gpopt/config/CConfigParamMapping.cpp` is the complete list of GUCs that reach
GPORCA, and every entry in it is an `optimizer_*` variable. `enable_hashjoin`,
`enable_nestloop`, `enable_mergejoin`, `enable_seqscan`, `enable_indexscan`,
`enable_hashagg` and the rest of the PostgreSQL family are **absent**. With
`optimizer = on` — the default — setting any of them has no effect on the plan whatsoever.

GPORCA has its own parallel set, and the polarity is the same (`off` disables the
operator):

| PostgreSQL knob | GPORCA equivalent | Default |
|---|---|---|
| `enable_hashjoin` | `optimizer_enable_hashjoin` | `on` |
| `enable_nestloop` | `optimizer_enable_nljoin` | `on` |
| `enable_mergejoin` | `optimizer_enable_mergejoin` | `on` |
| `enable_seqscan` | `optimizer_enable_tablescan` | `on` |
| `enable_indexscan` | `optimizer_enable_indexscan` | `on` |
| `enable_hashagg` | `optimizer_enable_hashagg` | `on` |
| `enable_sort` | `optimizer_enable_sort` | `on` |
| — | `optimizer_enable_motion_broadcast` | `on` |
| — | `optimizer_enable_motion_redistribute` | `on` |

The last two have no PostgreSQL counterpart and are the interesting ones for MPP: turning
`optimizer_enable_motion_broadcast` off is a diagnostic for "is this plan slow because of
the broadcast?", not a production setting.

**Incorrect (a PostgreSQL reflex that silently does nothing):**

```sql
-- Bad: optimizer defaults to on, so this changes exactly nothing.
SET enable_nestloop = off;
EXPLAIN (COSTS OFF) SELECT * FROM orders o JOIN customers c USING (customer_id);
--  Optimizer: GPORCA        <- the plan is identical
```

**Correct (use the knob that belongs to the optimizer that is running):**

```sql
-- Good: check which optimizer is active, then use its own GUC.
SHOW optimizer;                       -- on
SET optimizer_enable_nljoin = off;
EXPLAIN (COSTS OFF) SELECT * FROM orders o JOIN customers c USING (customer_id);
RESET optimizer_enable_nljoin;
```

Both families are last-resort diagnostics, not fixes. Disabling an operator does not make
the plan correct — it makes the optimizer pick its second choice from the same bad
estimates. Work `plan-estimate-vs-actual-means-stats` and `stats-analyze-explicitly-after-every-load`
first; reach for an `enable`-style GUC only to prove a hypothesis about *why* a plan is
slow, then take it back out.

Most `optimizer_*` GUCs carry `GUC_NOT_IN_SAMPLE`, which only keeps them out of
`postgresql.conf.sample` (`src/include/utils/guc.h`) — every GUC in the table above is
still visible, so `SELECT * FROM pg_settings WHERE name LIKE 'optimizer\_enable%';` lists
them all. The flag that hides a GUC from `SHOW ALL` and `pg_settings` is `GUC_NO_SHOW_ALL`
(`optimizer_print_missing_stats` and `gp_enable_explain_allstat` have it); those you must
ask for by name, e.g. `SHOW optimizer_print_missing_stats;`.

Reference: [Server configuration parameters (GUCs) overview](https://greengagedb.org/en/docs-gg/current/reference/guc_reference.html)
