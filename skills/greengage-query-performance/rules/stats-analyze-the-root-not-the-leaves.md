---
title: ANALYZE the root of a partitioned table, never a mid-level partition
impact: HIGH
impactDescription: "GPORCA plans partitioned tables from root statistics; without them it cannot size partition elimination and picks broadcasts over redistributes"
tags: [query-performance, statistics, partitioning, analyze]
---

## `ANALYZE` the root of a partitioned table, never a mid-level partition

**Impact: HIGH**

Root statistics on a partitioned table are **derived by merging the leaf statistics**, not
by sampling the whole table. `src/backend/commands/analyze.c` says so directly: "When we
have a root partition, we use the leaf partition statistics to derive root table
statistics. In that case, we do not need to collect a sample." So `ANALYZE <root>` walks
the leaves, analyzes them, and merges upward — which is why you point `ANALYZE` at the
root and let it do the traversal.

Mid-level partitions are refused with a warning, from `src/backend/commands/vacuum.c`:

```
WARNING:  skipping "orders_1_prt_2024" --- cannot analyze a mid-level partition.
          Please run ANALYZE on the root partition table.
```

Two GUCs govern the traversal, both `USERSET`:

| GUC | Default | Effect |
|---|---|---|
| `optimizer_analyze_root_partition` | `true` | collect statistics on the root partition during `ANALYZE`; with `false`, `ANALYZE <root>` analyzes the children and skips the root itself |
| `optimizer_analyze_midlevel_partition` | `false` | collect statistics on intermediate partitions |

Greengage also has three non-standard `ANALYZE` forms for exactly this, all present on 7.x
(`src/backend/parser/gram.y`):

```sql
ANALYZE ROOTPARTITION orders;      -- root statistics only, for this table
ANALYZE ROOTPARTITION ALL;         -- root statistics only, whole database
ANALYZE FULLSCAN orders;           -- scan every row instead of sampling
ANALYZE (FULLSCAN) orders;         -- the modern parenthesised spelling, 7.x only
```

All four work on 7.x. 6.x has the three unparenthesised forms; its `AnalyzeStmt` grammar
has no generic option list at all, so `ANALYZE (FULLSCAN)` is a 7.x addition. On both lines
the keywords must be followed by a relation name (or `ALL`, for `ROOTPARTITION` only —
there is no `ANALYZE FULLSCAN ALL`). `ROOTPARTITION` and `FULLSCAN` are unreserved
keywords, so a bare `ANALYZE ROOTPARTITION;` is not a syntax error: it is parsed as
`ANALYZE` of a table *named* `rootpartition` and fails with
`relation "rootpartition" does not exist`. The `gram.y` comment says why the option cannot
stand alone: "it is ambiguous whether 'ANALYZE ROOTPARTITION' means 'all relations with
ROOTPARTITION option', or 'one relation called ROOTPARTITION'".

**Incorrect (analyzing individual partitions and skipping the root):**

```sql
-- Bad: the leaves get statistics, the root gets none, and GPORCA plans the
-- whole partitioned table from an empty root.
ANALYZE orders_1_prt_2024_01;
ANALYZE orders_1_prt_2024_02;
ANALYZE orders_1_prt_2024_03;
```

**Correct (analyze the root and let it traverse):**

```sql
-- Good: analyzes the leaves and merges their statistics into the root.
ANALYZE orders;
```

```sql
-- Good: after loading one new partition, refresh that leaf and then just the
-- root's merged statistics - far cheaper than re-analyzing every leaf.
ANALYZE orders_1_prt_2024_04;
ANALYZE ROOTPARTITION orders;
```

`analyzedb` does the same thing by default; `--skip_orca_root_stats` turns the root-stats
generation off if you know you are not using GPORCA. Verify the root actually has
statistics with `SELECT count(*) FROM pg_stats WHERE tablename = 'orders';` — the root is a
relation in its own right and gets its own `pg_statistic` rows.

Reference: [How to collect statistics via ANALYZE](https://greengagedb.org/en/docs-gg/current/statistics_analyze.html)
