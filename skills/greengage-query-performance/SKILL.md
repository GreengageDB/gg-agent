---
name: greengage-query-performance
description: Diagnose and fix slow queries on a Greengage MPP cluster - EXPLAIN motions (Gather, Redistribute, Broadcast), slices and gangs, per-segment rows, GPORCA vs the Postgres planner and its silent fallback, data and computational skew, ANALYZE and analyzedb, statement_mem and workfile spill. Use when a query is slow, one segment lags, or you paste `Workfile: (3 spilling)`, `Memory wanted:`, `workfile per query size limit exceeded`, or `GPORCA failed to produce a plan, falling back to Postgres-based planner`.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "7.x (6.x deltas noted)"
---

# Greengage query performance

A rule library for making queries fast on a Greengage cluster, and for reading the plans
that say why they are not. `SKILL.md` is the router: work the diagnostic procedure, then
load the one rule file the symptom points at.

## Your PostgreSQL instincts are wrong in four specific ways

| PostgreSQL instinct | What Greengage actually does |
|---|---|
| The plan tree is one process's work | The tree is cut into **slices** at every `Motion`; each slice runs on a **gang** of one process per segment, all at once |
| `rows=` in `EXPLAIN ANALYZE` is the row count | Below a Motion it is the count from the **single busiest segment**, not the total (`src/backend/commands/explain_gp.c`: `instr->ntuples = ntuples.nsimax->ntuples`) |
| Cost tells you which plan is better | Two optimizers ship in the box and their cost units are **not comparable**; and GPORCA silently hands the query to the Postgres planner |
| A slow query means a bad plan | A perfect plan still runs at the speed of the **slowest segment**; skew beats plan quality every time |

The fifth difference is that nothing analyzes for you: `gp_autostats_mode` defaults to
`none` (`src/backend/utils/misc/guc_gp.c`), and on 6.x autovacuum does not run on
connectable databases at all.

## The diagnostic procedure

Do these in order. Steps 1-3 are cheap and eliminate most causes; do not skip to step 6.

**1. Measure, do not guess.** Get a wall-clock number first, with `\timing` in `psql` or
`EXPLAIN (ANALYZE, VERBOSE)`. `EXPLAIN` alone gives you estimates, and estimates are the
thing under suspicion. See `plan-explain-analyze-executes-the-statement` before running it
against DML.

```sql
\timing on
EXPLAIN (ANALYZE, VERBOSE) <your query>;
```

Keep `COSTS` on here. `COSTS OFF` suppresses the estimated `rows=`, which is exactly the
number step 5 compares against the actual — only turn it off when comparing optimizers,
where the cost numbers are meaningless anyway.

**2. Read the bottom of the plan before the top.** In this order: the `Optimizer:` line,
the `Memory wanted:` line, the `(sliceN)` statistics lines. Those three lines answer
"which planner produced this", "did it spill", and "which slice was expensive" before you
have parsed a single node. See `plan-optimizer-line-is-not-optional` and
`plan-spill-lines-name-the-fix`.

**3. Read the motions.** Every `Redistribute Motion` and `Broadcast Motion` is network
traffic that a better distribution key could have removed. Count them, note their `N:M`
sender:receiver numbers, and note which join they sit under. See
`plan-read-the-motions-first` and `plan-count-slices-not-nodes`.

**4. Check for skew before you touch the plan.** Count rows per `gp_segment_id` on the
tables involved, and compare `avg` against `max` on the slice lines. If one segment holds
or produces 5x its share, stop tuning the plan — fix the skew.
See `skew-measure-rows-per-segment-directly` and
`skew-computational-skew-is-not-data-skew`.

**5. Check the statistics.** A node whose estimate is off by more than ~10x is a
statistics problem wearing a planner costume. `gp_toolkit.gp_stats_missing` names tables
with none at all. See `plan-estimate-vs-actual-means-stats` and
`stats-find-missing-stats-before-tuning`.

**6. Run the same query under the other optimizer** — measured time and plan shape only,
never cost. See `opt-compare-optimizers-by-measuring-both`.

**7. Only now look upstream at the schema.** A motion you cannot remove by rewriting SQL
is a distribution-key decision. Hand off to
[greengage-schema-design](../greengage-schema-design/SKILL.md).

## Priority table

| Priority | Category | Impact | Prefix | Count |
|---|---|---|---|---|
| 1 | Reading MPP plans | CRITICAL | `plan-` | 7 |
| 2 | Skew | CRITICAL | `skew-` | 4 |
| 3 | The two optimizers | HIGH | `opt-` | 5 |
| 4 | Statistics | HIGH | `stats-` | 5 |
| 5 | Query patterns that hurt on MPP | HIGH | `sql-` | 7 |
| 6 | Memory and spill | MEDIUM-HIGH | `mem-` | 4 |

Section rationale is in [rules/_sections.md](rules/_sections.md); the skeleton for a new
rule is [rules/_template.md](rules/_template.md).

## Quick reference

### `plan-` Reading MPP plans (CRITICAL)

| Rule | One line |
|---|---|
| [plan-read-the-motions-first](rules/plan-read-the-motions-first.md) | `Gather`, `Redistribute` and `Broadcast Motion` are the only nodes that cost network; read them before scans and joins |
| [plan-actual-rows-are-segment-max](rules/plan-actual-rows-are-segment-max.md) | `rows=` below a Motion is the busiest segment's count, not the total — multiply, do not read literally |
| [plan-optimizer-line-is-not-optional](rules/plan-optimizer-line-is-not-optional.md) | Read `Optimizer:` on every plan; GPORCA falls back to the Postgres planner without saying so |
| [plan-count-slices-not-nodes](rules/plan-count-slices-not-nodes.md) | Slices are the unit of parallelism and of process count; `EXPLAIN (SLICETABLE)` prints them (7.x) |
| [plan-estimate-vs-actual-means-stats](rules/plan-estimate-vs-actual-means-stats.md) | A big estimate/actual gap is a statistics bug; fix stats before touching planner GUCs |
| [plan-spill-lines-name-the-fix](rules/plan-spill-lines-name-the-fix.md) | `Workfile: (N spilling)`, `Memory wanted:` and the `*` slice marker tell you exactly how much memory was missing |
| [plan-explain-analyze-executes-the-statement](rules/plan-explain-analyze-executes-the-statement.md) | `EXPLAIN ANALYZE` runs the statement on every segment; wrap DML in `BEGIN; ... ROLLBACK;` |

### `skew-` Skew (CRITICAL)

| Rule | One line |
|---|---|
| [skew-measure-rows-per-segment-directly](rules/skew-measure-rows-per-segment-directly.md) | `GROUP BY gp_segment_id` is the ground truth for data skew; run it before any other diagnosis |
| [skew-computational-skew-is-not-data-skew](rules/skew-computational-skew-is-not-data-skew.md) | Evenly stored data can still process unevenly; look at the join and group keys, not the distribution key |
| [skew-toolkit-views-scan-every-table](rules/skew-toolkit-views-scan-every-table.md) | `gp_skew_coefficients` and `gp_skew_idle_fractions` full-scan every user table — never run them casually on production |
| [skew-read-avg-versus-max-in-explain-analyze](rules/skew-read-avg-versus-max-in-explain-analyze.md) | `avg x N workers, ... max (segN)` on the slice lines is a free skew signal in every `EXPLAIN ANALYZE` |

### `opt-` The two optimizers (HIGH)

| Rule | One line |
|---|---|
| [opt-never-compare-costs-across-optimizers](rules/opt-never-compare-costs-across-optimizers.md) | GPORCA and the Postgres planner use different cost units; comparing the numbers is meaningless |
| [opt-detect-silent-orca-fallback](rules/opt-detect-silent-orca-fallback.md) | `SET optimizer_trace_fallback = on` turns the silent fallback into an `INFO` line naming the unsupported feature |
| [opt-compare-optimizers-by-measuring-both](rules/opt-compare-optimizers-by-measuring-both.md) | Run the query both ways in one session and compare measured time and plan shape |
| [opt-postgres-enable-flags-do-nothing-under-gporca](rules/opt-postgres-enable-flags-do-nothing-under-gporca.md) | `enable_nestloop` and friends steer only the Postgres planner; GPORCA has its own `optimizer_enable_*` set |
| [opt-switch-optimizers-per-session-first](rules/opt-switch-optimizers-per-session-first.md) | Change `optimizer` with `SET` for one query before changing it cluster-wide with `gpconfig` |

### `stats-` Statistics (HIGH)

| Rule | One line |
|---|---|
| [stats-analyze-explicitly-after-every-load](rules/stats-analyze-explicitly-after-every-load.md) | `gp_autostats_mode` is `none` by default — no load path collects statistics for you |
| [stats-find-missing-stats-before-tuning](rules/stats-find-missing-stats-before-tuning.md) | `gp_toolkit.gp_stats_missing` and the GPORCA `NOTICE` name the tables to fix first |
| [stats-analyze-the-root-not-the-leaves](rules/stats-analyze-the-root-not-the-leaves.md) | On a partitioned table, `ANALYZE` the root; mid-level partitions are skipped with a `WARNING` |
| [stats-analyzedb-is-incremental-only-for-append-optimized](rules/stats-analyzedb-is-incremental-only-for-append-optimized.md) | `analyzedb` re-analyzes every heap table on every run; the incremental win exists only for AO tables |
| [stats-analyze-only-the-columns-the-planner-uses](rules/stats-analyze-only-the-columns-the-planner-uses.md) | Column lists cut `ANALYZE` time on wide tables without hurting plans |

### `sql-` Query patterns that hurt on MPP (HIGH)

| Rule | One line |
|---|---|
| [sql-join-on-the-distribution-key](rules/sql-join-on-the-distribution-key.md) | A join whose keys are not both distribution keys pays a Redistribute or Broadcast on every run |
| [sql-do-not-wrap-the-join-key-in-a-function](rules/sql-do-not-wrap-the-join-key-in-a-function.md) | `ON a.id::text = b.id::text` destroys co-location even when both sides are distributed on `id` |
| [sql-order-by-without-limit-serializes-on-the-coordinator](rules/sql-order-by-without-limit-serializes-on-the-coordinator.md) | Every ordered row funnels through one process; add `LIMIT` so the sort limit is pushed to the segments |
| [sql-select-only-the-columns-you-need](rules/sql-select-only-the-columns-you-need.md) | On `orientation=column` tables `SELECT *` reads every column file instead of the two you wanted |
| [sql-count-distinct-costs-a-redistribute](rules/sql-count-distinct-costs-a-redistribute.md) | One `DISTINCT` aggregate is planned in stages; two of them drop GPORCA to the Postgres planner |
| [sql-keep-partition-predicates-on-the-bare-key](rules/sql-keep-partition-predicates-on-the-bare-key.md) | `WHERE date_trunc('day', ts) = ...` scans every partition; a range on the bare column does not |
| [sql-decorrelate-subqueries](rules/sql-decorrelate-subqueries.md) | A correlated subquery becomes a per-outer-row SubPlan or an outright `ERROR` on distributed tables |

### `mem-` Memory and spill (MEDIUM-HIGH)

| Rule | One line |
|---|---|
| [mem-size-statement-mem-from-memory-wanted](rules/mem-size-statement-mem-from-memory-wanted.md) | `Memory wanted:` is the measured answer; do not guess a `statement_mem` value |
| [mem-raise-statement-mem-per-session-not-globally](rules/mem-raise-statement-mem-per-session-not-globally.md) | `statement_mem` is charged on every segment for every concurrent statement; raise it in the session |
| [mem-cap-runaway-spill-with-workfile-limits](rules/mem-cap-runaway-spill-with-workfile-limits.md) | `gp_workfile_limit_per_query` kills a query before it fills the segment disks |
| [mem-find-the-spilling-query-with-gp-toolkit](rules/mem-find-the-spilling-query-with-gp-toolkit.md) | `gp_toolkit.gp_workfile_usage_per_query` names the session filling the disk, right now |

## How to apply this skill

1. Work the diagnostic procedure above until a step produces a signal.
2. Load **one** rule file by id — they are self-contained and each has a runnable
   Incorrect/Correct SQL pair.
3. Apply the fix at the lowest level that works: rewrite the SQL (`sql-`), then refresh
   statistics (`stats-`), then adjust session memory (`mem-`), then switch optimizer
   (`opt-`). Change the schema last, because it costs a full table rewrite.
4. Re-measure with the same `EXPLAIN (ANALYZE, VERBOSE)` you started with. A change you
   did not measure did not happen.

For the annotated walkthrough of real Greengage `EXPLAIN` and `EXPLAIN ANALYZE` output —
every MPP-specific line named and explained — read
[reference/explain-reading.md](reference/explain-reading.md).

## Traps that do not fit a single rule

**The `EXPLAIN` you ran is not the plan that ran.** `EXPLAIN` without `ANALYZE` plans with
the current GUCs and current statistics. If someone changed `optimizer`, `statement_mem`
or ran `ANALYZE` between the slow run and your investigation, you are looking at a
different plan. Reproduce with `EXPLAIN (ANALYZE)` in the same session, with the same
GUCs, before believing anything.

**`gp_segment_id` does not exist on `DISTRIBUTED REPLICATED` tables.** System columns are
deliberately not exposed for replicated tables
(`src/backend/parser/parse_relation.c`: "for replicated table, we don't expose system
columns"), so the standard skew query fails with `column "gp_segment_id" does not exist`.
That is correct behaviour, not a bug: every segment holds a full copy, so skew is zero by
construction.

**A plan with no Motion at all is a warning sign, not a prize.** With `EXPLAIN
(SLICETABLE)` on 7.x it shows as a single `Slice 0: Dispatcher; ... gang size 0`. It means
the query ran entirely on the coordinator — a catalog-only query, a `FROM` list of
coordinator-only relations, or a function declared `EXECUTE ON COORDINATOR`. The segments
are idle and the cluster is a single PostgreSQL server for the duration.

**Costs are per-plan-tree, not per-segment.** The `cost=` numbers describe the work of one
slice on one segment. Do not multiply them by the segment count and do not compare them to
a single-node PostgreSQL plan for the same data.

**6.x prints different labels for the same things.** The `Optimizer:` line reads
`Postgres query optimizer` / `Pivotal Optimizer (GPORCA)` on 6.x and
`Postgres-based planner` / `GPORCA` on 7.x
(`src/backend/commands/explain.c`). `EXPLAIN (SLICETABLE)` is 7.x-only. Grep for whichever
pair your cluster prints.

**Resource management can override your memory settings.** With
`gp_resource_manager = group`, per-statement memory comes from the resource group, not
only from `statement_mem`. Diagnose there first — see
[greengage-workload-management](../greengage-workload-management/SKILL.md).

## What not to do, and noise to ignore

- **Do not start by setting planner GUCs.** `enable_hashjoin=off` and friends are a last
  resort, they only affect one of the two optimizers, and they hide the real cause
  (`opt-postgres-enable-flags-do-nothing-under-gporca`).
- **Do not compare `cost=` numbers between a GPORCA plan and a Postgres-planner plan.**
  They are different currencies (`opt-never-compare-costs-across-optimizers`).
- **Do not run `gp_toolkit.gp_skew_coefficients` on a busy production cluster** to "have a
  look". It sequentially scans every user table (`skew-toolkit-views-scan-every-table`).
- **Ignore `Settings:` unless it names something you did not set.** It lists non-default
  planning GUCs and is usually just `optimizer = 'off'` from the session you are in. It is
  printed only under `VERBOSE` or `EXPLAIN (SETTINGS)` (`ExplainPrintSettings()` returns
  early otherwise), so its absence from a plain plan means nothing.
- **Ignore `(never executed)`** on the inner side of a join whose outer side returned zero
  rows. It means the node was correctly skipped, not that it failed.
- **Ignore `Buffers:` for cross-segment reasoning.** Like `rows=`, it is copied from the
  single segment that produced the most rows (`explain_gp.c`:
  `instr->bufusage = ntuples.nsimax->bufusage`), so it says nothing about total cluster I/O.
- **Do not chase `Planning Time:` unless it dominates `Execution Time:`.** When it does,
  the usual causes are a very large partition count and GPORCA's exhaustive join search
  (`optimizer_join_order` defaults to `exhaustive2` on 7.x and `exhaustive` on 6.x, up to
  `optimizer_join_order_threshold` = 10 join children). Both are schema-shaped problems for
  [greengage-schema-design](../greengage-schema-design/SKILL.md), not query problems.

See also: [greengage-schema-design](../greengage-schema-design/SKILL.md),
[greengage-workload-management](../greengage-workload-management/SKILL.md),
[greengage-overview](../greengage-overview/SKILL.md),
[greengage-internals](../greengage-internals/SKILL.md),
[greengage-data-loading](../greengage-data-loading/SKILL.md),
[greengage-cluster-ops](../greengage-cluster-ops/SKILL.md)
