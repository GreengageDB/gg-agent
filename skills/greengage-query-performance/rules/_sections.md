# Rule sections

Each section id is the filename prefix of its rules. Load `<prefix>-<name>.md` to get one
rule; the priority table in `../SKILL.md` maps sections to counts and gives every rule a
one-line summary.

| Prefix | Title | Impact | Rules |
|---|---|---|---|
| `plan-` | Reading MPP plans | CRITICAL | 7 |
| `skew-` | Skew | CRITICAL | 4 |
| `opt-` | The two optimizers | HIGH | 5 |
| `stats-` | Statistics | HIGH | 5 |
| `sql-` | Query patterns that hurt on MPP | HIGH | 7 |
| `mem-` | Memory and spill | MEDIUM-HIGH | 4 |

---

## `plan-` — Reading MPP plans

**Impact: CRITICAL**

Every performance decision downstream depends on reading the plan correctly, and a
Greengage plan encodes things a PostgreSQL plan never had to. The tree is cut into
**slices** at every `Motion` node, and each slice is executed simultaneously by a **gang**
of one process per segment, so a plan with four Motions is four rounds of network traffic
and up to five process groups per query. The three Motion types have wildly different
costs: `Gather Motion` funnels every row into one coordinator process, `Redistribute
Motion` rehashes rows across the interconnect, and `Broadcast Motion` sends **every** row
to **every** segment — an N-fold multiplication of data volume that is cheap for a
thousand-row dimension and catastrophic for a fact table.

The statistics are read differently too. `src/backend/commands/explain_gp.c` copies the
stats of the segment with the **most rows** into the coordinator's `Instrumentation`
struct (`instr->ntuples = ntuples.nsimax->ntuples`), so `rows=` under a Motion is a
per-segment maximum, not a total; an analyst who reads it as a total will conclude the
planner is off by a factor of N. Memory and spill appear as their own lines
(`Workfile: (N spilling)`, `Work_mem wanted:`, `Memory wanted:`), and the `Optimizer:`
line at the end of the tree is the only place the plan tells you which of the two
optimizers actually produced it — GPORCA falls back to the Postgres planner without a
word unless you asked it to speak.

## `skew-` — Skew

**Impact: CRITICAL**

An MPP query finishes when its slowest segment finishes. If one segment out of 24 holds
five times its share of a table, that query takes five times as long as it should no
matter how good the plan is, and no amount of `statement_mem` or optimizer switching will
recover it. This makes skew the one condition that invalidates every other measurement:
tune a plan on a skewed table and you are measuring the skew.

Two distinct failures wear the same name. **Data skew** is uneven storage — a
low-cardinality or nullable distribution key concentrates rows on a few segments; it is
measured directly by counting rows per `gp_segment_id`, and by
`gp_toolkit.gp_skew_coefficients` (coefficient of variation of the per-segment row counts,
as a percentage) and `gp_toolkit.gp_skew_idle_fractions`. **Computational skew** is uneven
*processing* on evenly stored data — a `GROUP BY` or join key whose values cluster, so
after a `Redistribute Motion` one segment holds most of the hash table; it is invisible in
the storage-skew views and only shows up as `avg x N workers ... max (segN)` divergence in
`EXPLAIN ANALYZE`. Both toolkit views loop over every user table and sequentially scan
each one, so they are a maintenance-window tool, not a monitoring query.

## `opt-` — The two optimizers

**Impact: HIGH**

Greengage ships two independent query optimizers and a single boolean switch between them.
`optimizer` defaults to `on` (GPORCA) in any build with `USE_ORCA`; `optimizer = off`
selects the PostgreSQL planner extended with MPP motion planning. They are not two modes
of one planner — they are separate code bases (`src/backend/gporca/` versus
`src/backend/optimizer/`) with separate cost models, so their `cost=` numbers are in
different units and comparing them is a category error. The only honest comparison is plan
*shape* and *measured* time.

The trap that costs the most investigation time is the fallback. When GPORCA cannot
translate a query it throws, gets caught in `src/backend/gpopt/CGPOptimizer.cpp`, and the
Postgres planner produces the plan instead — silently, because the `INFO` message is gated
on `optimizer_trace_fallback`, which is `false` by default. So `optimizer = on` does not
mean the plan came from GPORCA, and a session where you "tested GPORCA" may never have
used it. The `Optimizer:` line on the plan and `SET optimizer_trace_fallback = on` are the
two ways to know. The same asymmetry applies to tuning knobs: `enable_hashjoin`,
`enable_nestloop` and the rest of the PostgreSQL `enable_*` family are not mapped into
GPORCA at all (`src/backend/gpopt/config/CConfigParamMapping.cpp` maps only
`optimizer_enable_*`), so half the tuning advice on the internet is inert here.

## `stats-` — Statistics

**Impact: HIGH**

Nothing in Greengage collects statistics on its own. `gp_autostats_mode` defaults to
`none`, so `CREATE TABLE AS`, `INSERT ... SELECT`, `COPY` and every external-table load
leave `pg_statistic` exactly as it was. On 6.x autovacuum is disabled outright for
connectable databases (`src/backend/postmaster/autovacuum.c`: "In GPDB, autovacuum is
currently disabled, except for the anti-wraparound vacuum of template0 ... The
administrator is expected to do all VACUUMing manually"); on 7.x it runs but
`gp_autovacuum_scope` defaults to `catalog`. Either way, a freshly loaded table has the
statistics of an empty table, and both optimizers will happily choose a `Broadcast Motion`
for a billion-row "small" side.

The MPP specifics on top of that: partitioned tables derive root statistics by *merging*
leaf statistics, so you `ANALYZE` the root and mid-level partitions are skipped with a
`WARNING`; `optimizer_analyze_root_partition` (default `true`) controls whether the root
gets stats at all, and GPORCA needs them. `analyzedb` is the incremental driver, but its
incrementality applies only to append-optimized tables — its own help text says "All heap
tables are regarded as having stale stats every time analyzedb is run." Missing statistics
announce themselves: GPORCA raises
`NOTICE: One or more columns in the following table(s) do not have statistics: ...`, and
`gp_toolkit.gp_stats_missing` lists them on demand.

## `sql-` — Query patterns that hurt on MPP

**Impact: HIGH**

The same SQL that is merely suboptimal on PostgreSQL can be order-of-magnitude wrong on a
cluster, because the cost is paid in network traffic rather than CPU. A join predicate
that is not on both tables' distribution keys forces a `Redistribute Motion` (rehash and
resend one side) or a `Broadcast Motion` (send one side to every segment) on **every
execution**; wrapping the key in a cast or function has the same effect even when the
columns are the distribution keys, because the hash no longer matches. `ORDER BY` without
`LIMIT` makes every result row pass through the single coordinator process. `SELECT *` on
an `orientation=column` table opens every column's segment file rather than the two the
query needs (`src/backend/access/aocs/aocsam.c` projects only `proj_atts`). `count(DISTINCT
...)` is planned in multiple aggregate stages with a redistribute in the middle, and a
*second* distinct aggregate in the same query hits
`optimizer_enable_multiple_distinct_aggs` (default `false`) and drops GPORCA to the
Postgres planner. Predicates that hide the partition key behind a function defeat
partition elimination and turn a one-partition scan into a full-table scan. Correlated
subqueries either get decorrelated, become a SubPlan executed once per outer row, or fail
outright with `correlated subquery with skip-level correlations is not supported`.

## `mem-` — Memory and spill

**Impact: MEDIUM-HIGH**

`statement_mem` (default `128000` kB, i.e. 125 MB) is the memory budget a single statement
gets **on each segment**, so a 2 GB setting on a 24-segment cluster is a 48 GB promise, and
raising it globally is how a cluster starts OOM-killing under concurrency. When an
operator exceeds its share it spills to work files on segment-local disk, which is
correct-but-slow behaviour, not an error: `Workfile: (N spilling)` in the node lines and
`Memory wanted:` in the summary tell you precisely how much more the statement needed.
That number is measured, so there is no reason to guess.

The blast radius is bounded by three GUCs that all default to unlimited or near-unlimited:
`gp_workfile_limit_per_query` (0 = no limit, kB, per segment),
`gp_workfile_limit_per_segment` (0 = no limit, postmaster-level) and
`gp_workfile_limit_files_per_query` (100000). Setting the first of these in a session is
the standard way to stop an exploratory query from filling the segment disks — it fails
with `ERROR: workfile per query size limit exceeded` instead. What is currently on disk is
visible in `gp_toolkit.gp_workfile_entries`, `gp_toolkit.gp_workfile_usage_per_query` and
`gp_toolkit.gp_workfile_usage_per_segment`, joined to `pg_stat_activity`, so you can name
the offending session while it is still running.
