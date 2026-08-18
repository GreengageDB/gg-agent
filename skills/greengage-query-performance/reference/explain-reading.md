# Reading a Greengage EXPLAIN plan, line by line

Lookup material: every MPP-specific line Greengage can print, what emits it, and what it
means. Methodology lives in [../SKILL.md](../SKILL.md).

## Where these shapes come from

Every plan fragment below is the real output shape taken from the 7.x regression expected
files, not an invention:

| File (`src/test/regress/expected/`) | Why it is authoritative |
|---|---|
| `explain_format.out`, `explain_format_optimizer.out` | routes `EXPLAIN` through a plpgsql `explain_filter()` function that replaces every number with `N`, so the result is a normal query result and is compared **literally** |
| `explain_analyze.out` | its plans sit between `-- explain_processing_off` and `-- explain_processing_on`, which disables `atmsort`'s plan normalisation, so those blocks are compared literally |
| `with.out` | the `EXPLAIN (SLICETABLE, COSTS OFF)` examples |
| `gp_dqa.out`, `gp_dqa_optimizer.out` | the distinct-aggregate plan shapes and the GPORCA fallback messages |
| `gp_explain.out` | the `*` slice marker and `Memory wanted:` example |

**Caveat when reading `.out` files yourself:** `src/test/regress/init_file` puts
`m/^ Optimizer status:.*/`, `m/^ Optimizer: Pivotal Optimizer \(GPORCA\).*/`,
`m/^ Optimizer: Postgres query optimizer/`, `m/^ Optimizer: GPORCA/`,
`m/^ Optimizer: Postgres-based planner/` and `m/^ Settings:.*/` in its `matchignore` list,
so those lines are never compared and stale text survives in expected files. The authority for the
optimizer string is `src/backend/commands/explain.c`, not the `.out` files. `gp_explain.out`
in particular still contains 6.x-era `Slice statistics:` / `Total runtime:` text that 7.x
does not emit, because `atmsort` normalises those blocks away.

## The output, in emission order (7.x)

`src/backend/commands/explain.c` `ExplainOnePlan()` emits, in this order:

1. the plan tree — `ExplainPrintPlan()`
2. `Optimizer: …` always, then `Settings: …` if `VERBOSE` or `SETTINGS` — the tail of
   `ExplainPrintPlan()`
3. `Planning Time: N ms` — when `SUMMARY` is on
4. the slice table — only with `EXPLAIN (SLICETABLE)`, 7.x only
5. trigger statistics — `ANALYZE` only
6. per-slice statistics, `Memory used:`, `Memory wanted:` — `ANALYZE` only,
   `src/backend/commands/explain_gp.c`
7. the JIT summary — when `gp_explain_jit` is on **and** `COSTS` is on
8. `Execution Time: N ms`

6.x emits the `Optimizer:` line **after** the slice statistics instead, inside its
`Settings` group.

## A full annotated `EXPLAIN (ANALYZE)` — Postgres planner

From `explain_format.out`, three-table left join, `explain_filter()` has replaced every
number with `N`:

```
 Gather Motion N:N  (sliceN; segments: N)  (cost=N.N..N.N rows=N width=N) (actual time=N.N..N.N rows=N loops=N)
   ->  Hash Left Join  (cost=N.N..N.N rows=N width=N) (actual time=N.N..N.N rows=N loops=N)
         Hash Cond: (boxes.location_id = box_locations.id)
         ->  Redistribute Motion N:N  (sliceN; segments: N)  (cost=N.N..N.N rows=N width=N) (actual time=N.N..N.N rows=N loops=N)
               Hash Key: boxes.location_id
               ->  Hash Left Join  (cost=N.N..N.N rows=N width=N) (actual time=N.N..N.N rows=N loops=N)
                     Hash Cond: (boxes.apple_id = apples.id)
                     ->  Redistribute Motion N:N  (sliceN; segments: N)  (cost=N.N..N.N rows=N width=N) (actual time=N.N..N.N rows=N loops=N)
                           Hash Key: boxes.apple_id
                           ->  Seq Scan on boxes  (cost=N.N..N.N rows=N width=N) (actual time=N.N..N.N rows=N loops=N)
                     ->  Hash  (cost=N.N..N.N rows=N width=N) (actual time=N.N..N.N rows=N loops=N)
                           Buckets: N  Batches: N  Memory Usage: NkB
                           ->  Seq Scan on apples  (cost=N.N..N.N rows=N width=N) (actual time=N.N..N.N rows=N loops=N)
         ->  Hash  (cost=N.N..N.N rows=N width=N) (actual time=N.N..N.N rows=N loops=N)
               Buckets: N  Batches: N  Memory Usage: NkB
               ->  Seq Scan on box_locations  (cost=N.N..N.N rows=N width=N) (actual time=N.N..N.N rows=N loops=N)
 Optimizer: Postgres-based planner
 Planning Time: N.N ms
   (sliceN)    Executor memory: NK bytes.
   (sliceN)    Executor memory: NK bytes avg x N workers, NK bytes max (segN).  Work_mem: NK bytes max.
   (sliceN)    Executor memory: NK bytes avg x N workers, NK bytes max (segN).  Work_mem: NK bytes max.
   (sliceN)    Executor memory: NK bytes avg x N workers, NK bytes max (segN).
 Memory used:  NkB
 Execution Time: N.N ms
```

Reading it: four slice lines means four slices — slice 0 on the coordinator plus three
segment gangs. Two `Redistribute Motion`s means neither join was co-located. `Buckets` /
`Batches` / `Memory Usage` are ordinary PostgreSQL hash-join lines; `Batches: 1` means the
hash fitted in memory. `Memory used:` is what the statement was granted, not what it
consumed, and no `Memory wanted:` line means nothing spilled.

## The same query under GPORCA

From `explain_format_optimizer.out`. Same SQL, same data, different join strategy — this
is why plan **shape** is the comparison and cost numbers are not:

```
 Gather Motion N:N  (sliceN; segments: N)  (cost=N.N..N.N rows=N width=N)
   ->  Nested Loop Left Join  (cost=N.N..N.N rows=N width=N)
         Join Filter: true
         ->  Redistribute Motion N:N  (sliceN; segments: N)  (cost=N.N..N.N rows=N width=N)
               Hash Key: boxes.apple_id
               ->  Nested Loop Left Join  (cost=N.N..N.N rows=N width=N)
                     Join Filter: true
                     ->  Redistribute Motion N:N  (sliceN; segments: N)  (cost=N.N..N.N rows=N width=N)
                           Hash Key: boxes.location_id
                           ->  Seq Scan on boxes  (cost=N.N..N.N rows=N width=N)
                     ->  Index Scan using box_locations_pkey on box_locations  (cost=N.N..N.N rows=N width=N)
                           Index Cond: (id = boxes.location_id)
         ->  Index Scan using apples_pkey on apples  (cost=N.N..N.N rows=N width=N)
               Index Cond: (id = boxes.apple_id)
 Optimizer: GPORCA
```

## Motion nodes

`src/backend/commands/explain.c` builds the node name as `"%s %d:%d"` — name, senders,
receivers.

| Printed | `MotionType` | Rows moved |
|---|---|---|
| `Gather Motion N:1` | `MOTIONTYPE_GATHER` | all rows into the single coordinator process |
| `Explicit Gather Motion N:1` | `MOTIONTYPE_GATHER_SINGLE` | "Execute subplan on N nodes, but only send the tuples from one" (`plannodes.h`) — used when the input has a replicated locus, where gathering from every segment would duplicate rows |
| `Redistribute Motion N:N` | `MOTIONTYPE_HASH` | each row rehashed on `Hash Key` and sent to its new owner |
| `Broadcast Motion N:N` | `MOTIONTYPE_BROADCAST` | every row to every segment — input volume x N |
| `Explicit Redistribute Motion N:N` | `MOTIONTYPE_EXPLICIT` | rows routed by `gp_segment_id`, used by `UPDATE` / `DELETE` |

Child lines under a Motion:

| Line | Meaning |
|---|---|
| `Hash Key: <cols>` | the columns being rehashed (Redistribute) |
| `Merge Key: <cols>` | the Motion has `sendSorted` set and is merging pre-sorted streams rather than concatenating — almost always a `Gather Motion` under a top-level `ORDER BY` |
| `Hash Module: <n>` | the Motion targets fewer segments than the receiving gang has |

A real `Broadcast Motion`, from `explain_analyze.out`. Read the `loops=` counts: the
`SubPlan` was re-evaluated 78 times, but the `Materialize` above the Motion cached the
broadcast result, so the Motion itself shows `loops=1` and crossed the interconnect once:

```
 Gather Motion 3:1  (slice1; segments: 3) (actual rows=2 loops=1)
   ->  Seq Scan on slice_test a (actual rows=2 loops=1)
         Filter: ((j = (SubPlan 1)) AND ((SubPlan 1) = i))
         Rows Removed by Filter: 74
         SubPlan 1
           ->  Result (actual rows=1 loops=78)
                 Filter: ((a.i = 0) OR (b.i = 0))
                 ->  Materialize (actual rows=1 loops=80)
                       ->  Broadcast Motion 3:3  (slice2; segments: 3) (actual rows=1 loops=1)
                             ->  Seq Scan on slice_test2 b (actual rows=1 loops=1)
 Optimizer: Postgres-based planner
 Planning Time: 0.662 ms
   (slice0)    Executor memory: 47K bytes.
   (slice1)    Executor memory: 43K bytes avg x 3 workers, 43K bytes max (seg0).  Work_mem: 17K bytes max.
   (slice2)    Executor memory: 37K bytes avg x 3 workers, 37K bytes max (seg0).
 Memory used:  128000kB
 Execution Time: 4.953 ms
```

## Slices and gangs

`show_dispatch_info()` prints the slice annotation on Motion nodes:

| Printed | Condition |
|---|---|
| `(sliceN; segments: M)` | the slice runs on M segments |
| `(sliceN)` | the slice has no segment gang — coordinator (`GANGTYPE_UNALLOCATED`) or entry-db reader |
| `(sliceN; gangM; segments: K)` | only when `gp_log_gang` is at `debug` |

`EXPLAIN (SLICETABLE, …)` — **7.x only** — prints one line per slice with its gang type,
from `ExplainPrintSliceTable()`. This example is from `with.out`:

```
 Gather Motion 3:1  (slice1; segments: 3)
   ->  Hash Join
         Hash Cond: (a.i = b.i)
         ->  Redistribute Motion 3:3  (slice2; segments: 3)
               Hash Key: a.i
               ->  Subquery Scan on a
                     ->  Shared Scan (share slice:id 2:0)
         ->  Hash
               ->  Redistribute Motion 3:3  (slice3; segments: 3)
                     Hash Key: b.i
                     ->  Subquery Scan on b
                           ->  Shared Scan (share slice:id 3:0)
                                 ->  Insert on with_test
                                       ->  Redistribute Motion 1:3  (slice4; segments: 1)
                                             ->  Result
 Optimizer: Postgres-based planner
 Slice 0: Dispatcher; root 0; parent -1; gang size 0
 Slice 1: Reader; root 0; parent 0; gang size 3
 Slice 2: Reader; root 0; parent 1; gang size 3
 Slice 3: Primary Writer; root 0; parent 1; gang size 3
 Slice 4: Singleton Reader; root 0; parent 3; gang size 1; segment N
```

Gang types, from `ExplainPrintSliceTable()`:

| Gang type | Meaning |
|---|---|
| `Dispatcher` | coordinator only, no segment processes (`GANGTYPE_UNALLOCATED`) |
| `Entry DB Reader` | reads coordinator-local relations |
| `Singleton Reader` | exactly one segment; the line ends `; segment <n>` |
| `Reader` | all segments, read-only |
| `Primary Writer` | all segments, holds the write locks — the query is doing DML |

Total segment processes for the query is the sum of the gang sizes. This plan uses
3 + 3 + 3 + 1 = 10 segment processes plus the coordinator.

## Per-node statistics under `ANALYZE`

The `(actual …)` group is standard PostgreSQL, with one MPP twist:
`src/backend/commands/explain_gp.c` copies the statistics of the segment with the **most
rows** (`ntuples.nsimax`) into the printed node. So below a Motion, `rows=` and `loops=`
are that one segment's numbers, not cluster totals.

| Line | Emitted when | Meaning |
|---|---|---|
| `Executor Memory: NkB  Segments: N  Max: NkB (segment N)` | node allocates its own memory context | per-node memory, summed across segments, with the worst segment named |
| `work_mem: NkB  Segments: N  Max: NkB (segment N)  Workfile: (N spilling)` | `ANALYZE` + `VERBOSE`, on Sort / HashJoin / hashed Agg / Material (`nodeSupportWorkfileCaching()`) | work memory summed over segments, then the worst segment, then how many segments spilled. The `Workfile:` clause is printed for every one of those node types, so `(0 spilling)` is the normal no-spill reading — read the count, not the presence |
| `Work_mem wanted: <size> avg, <size> max (segN) to lessen workfile I/O affecting N workers.` | `ANALYZE` + `VERBOSE`, and something spilled | the work memory this node needed |
| `Sort Method:  quicksort  Memory: NkB` | Sort node under `ANALYZE` | `external merge` and `Disk:` instead of `quicksort` and `Memory:` mean this sort spilled; the size is the **sum** over segments |
| `  Max Memory: NkB  Avg Memory: NkB (N segments)` | appended to the Sort Method line under `VERBOSE` | max and average over segments. The labels say "Memory" even when the space type on the same line is `Disk` — that is hardcoded in `show_sort_info()`, not a sign the sort stayed in memory |
| `Partitions scanned:  Avg N.N x N workers.  Max N parts (segN).` | dynamic partition scan | how many partitions survived elimination |
| `(never executed)` | node's parent never pulled from it | not a failure |
| `allstat: seg_firststart_total_ntuples/seg0_…/seg1_…` | `gp_enable_explain_allstat = on` | every segment's start time, total time and row count for this node |

A Sort node carrying the full set of memory lines, from `explain_format.out` (this
particular sort did **not** spill — `Sort Method: quicksort  Memory:` says so, and
`explain_filter()` has masked the `Workfile:` count along with every other number):

```
Gather Motion N:N  (sliceN; segments: N)  (cost=N.N..N.N rows=N width=N) (actual time=N.N..N.N rows=N loops=N)
  Output: id, apple_id, location_id
  Merge Key: apple_id
  ->  Sort  (cost=N.N..N.N rows=N width=N) (actual time=N.N..N.N rows=N loops=N)
        Output: id, apple_id, location_id
        Sort Key: boxes.apple_id
        Sort Method:  quicksort  Memory: NkB  Max Memory: NkB  Avg Memory: NkB (N segments)
        Executor Memory: NkB  Segments: N  Max: NkB (segment N)
        work_mem: NkB  Segments: N  Max: NkB (segment N)  Workfile: (N spilling)
        ->  Seq Scan on public.boxes  (cost=N.N..N.N rows=N width=N) (actual time=N.N..N.N rows=N loops=N)
              Output: id, apple_id, location_id
Optimizer: Postgres-based planner
Settings: cpu_index_tuple_cost = 'N.N', optimizer = 'off', random_page_cost = 'N'
Planning Time: N.N ms
  (sliceN)    Executor memory: NK bytes.
  (sliceN)    Executor memory: NK bytes avg x N workers, NK bytes max (segN).  Work_mem: NK bytes max.
Memory used:  NkB
Execution Time: N.N ms
```

## The slice summary and the memory summary

From `gpexplain_formatSlicesOutput()` and `cdbexplain_showExecStatsEnd()` in
`src/backend/commands/explain_gp.c`. This example is from `gp_explain.out` and shows the
markers:

```
   (slice0)    Executor memory: 156K bytes.
 * (slice1)    Executor memory: 94K bytes avg x 3 workers, 100K bytes max (seg1).  Work_mem: 65K bytes max, 1K bytes wanted.
   (slice2)    Executor memory: 151K bytes.
 _ (slice3)    Workers: Workers: 3 not dispatched;.
 Executor memory: 75K bytes avg x 3 workers, 75K bytes max (seg0).
 Memory used:  128000kB
 Memory wanted:  800kB
```

| Element | Meaning |
|---|---|
| `*` before `(sliceN)` | this slice wanted more work memory than it got — the code sets the marker exactly when `workmemwanted_max > 0` |
| `_` before `(sliceN)` | some workers of this slice were never dispatched |
| `X` before `(sliceN)` | some workers of this slice reported an error |
| `avg x N workers, … max (segN)` | memory spread across the gang; `segN` is the worst segment |
| `Work_mem: X max, Y wanted.` | the largest work-memory use and want anywhere in this slice |
| `Vmem reserved: …` | only with `explain_memory_verbosity = summary` or higher |
| `Workers: N not dispatched` | the slice was planned but never dispatched (an unused InitPlan branch, for instance) |
| `Memory used:` | `stmt->query_mem`, the query memory **granted** to the statement — **not** consumption. Under the default resource-queue policy that is `statement_mem`; under `gp_resource_manager = group` the resource group sets it |
| `Memory wanted:` | printed only when something spilled: the `statement_mem` that would have avoided all spilling |

## The `Optimizer:` and `Settings:` lines

| Line | 7.x | 6.x |
|---|---|---|
| Postgres planner | `Optimizer: Postgres-based planner` | `Optimizer: Postgres query optimizer` |
| GPORCA | `Optimizer: GPORCA` | `Optimizer: Pivotal Optimizer (GPORCA)` |

`Settings:` lists planning GUCs whose value differs from the built-in default, e.g.
`Settings: cpu_index_tuple_cost = 'N.N', optimizer = 'off', random_page_cost = 'N'`.
`ExplainPrintSettings()` returns immediately unless `VERBOSE` or the `SETTINGS` option is
on, so a plain `EXPLAIN` never prints it — under `VERBOSE` you get the Greengage planner
GUCs plus `work_mem` (`gp_guc_list_for_explain`), under `SETTINGS` the upstream
`GUC_EXPLAIN` set. It is usually noise; read it only to spot a GUC you did not set yourself.

A fallback from GPORCA is announced only with `optimizer_trace_fallback = on`, and looks
like this (`gp_dqa_optimizer.out`):

```
INFO:  GPORCA failed to produce a plan, falling back to Postgres-based planner
DETAIL:  Falling back to Postgres-based planner because GPORCA does not support the following feature: Multiple Distinct Qualified Aggregates are disabled in the optimizer
```

On 6.x the first line is `GPORCA failed to produce a plan, falling back to planner`.

## Greengage-only plan nodes you will meet

| Node | Emitted for |
|---|---|
| `Motion` (five spellings above) | every slice boundary |
| `Partition Selector` | dynamic partition elimination, mostly under GPORCA |
| `Dynamic Seq Scan`, `Dynamic Index Scan`, `Dynamic Bitmap Heap Scan` | scans whose partition set is decided at run time |
| `Shared Scan (share slice:id A:B)` | a CTE or subplan materialised once and read by several slices |
| `Split` (`SplitUpdate`) | an `UPDATE` that changes a distribution key column, split into delete + insert |
| `Assert` (`AssertOp`) | a run-time constraint check inserted by GPORCA |
| `Sequence` | GPORCA's ordered execution of a partition selector followed by its scan |
| `TupleSplit` + `Streaming HashAggregate` | multiple distinct aggregates on the Postgres-planner path |
| `Finalize Aggregate` / `Partial Aggregate` | multi-stage aggregation across a Motion |
| `Subplans Removed: N` | PostgreSQL run-time partition pruning (7.x) |

Distinct-aggregate shapes, from `gp_dqa.out` (`dqa_t1` is distributed on `d`).
`count(distinct d)` — distinct key **is** the distribution key, so no extra Motion:

```
 Finalize Aggregate
   ->  Gather Motion 3:1  (slice1; segments: 3)
         ->  Partial Aggregate
               ->  Seq Scan on dqa_t1
```

`count(distinct c)` — distinct key is **not** the distribution key, so local
de-duplication, redistribute on the distinct key, re-aggregate:

```
 Finalize Aggregate
   ->  Gather Motion 3:1  (slice1; segments: 3)
         ->  Partial Aggregate
               ->  HashAggregate
                     Group Key: c
                     ->  Redistribute Motion 3:3  (slice2; segments: 3)
                           Hash Key: c
                           ->  Streaming HashAggregate
                                 Group Key: c
                                 ->  Seq Scan on dqa_t1
```

Two distinct aggregates over **different** columns (`count(distinct d), count(distinct dt)`)
— GPORCA has fallen back, and the Postgres planner uses `TupleSplit`:

```
 Finalize Aggregate
   ->  Gather Motion 3:1  (slice1; segments: 3)
         ->  Partial Aggregate
               ->  Redistribute Motion 3:3  (slice2; segments: 3)
                     Hash Key: d, dt, (AggExprId)
                     ->  Streaming HashAggregate
                           Group Key: AggExprId, d, dt
                           ->  TupleSplit
                                 Split by Col: (d), (dt)
                                 ->  Seq Scan on dqa_t1
```

## Structured output

`FORMAT JSON | YAML | XML` carries the same information as named properties, which is what
to parse if you are automating. The MPP-specific keys, from `explain_format.out`:

```
- Plan:
    Node Type: "Gather Motion"
    Senders: N
    Receivers: N
    Slice: N
    Segments: N
    Gang Type: "primary reader"
    ...
  Slice statistics:
    - Slice: N
      Executor Memory:
        Average: N
        Workers: N
        Maximum Memory Used: N
      Work Maximum Memory: N
  Statement statistics:
    Memory used: N
  Execution Time: N.N
```

A minimal JSON example, also from `explain_format.out`:

```json
[{"Plan": {"Alias": "generate_series", "Slice": 0, "Segments": 0,
           "Gang Type": "unallocated", "Node Type": "Function Scan",
           "Function Name": "generate_series", "Parallel Aware": false},
  "Optimizer": "Postgres-based planner"}]
```

Keys that only the structured formats spell out: `Workfile Spilling`, `Max Memory Wanted`,
`Avg Memory Wanted`, `Segments Affected`, `Virtual Memory`.

## GUCs that change what `EXPLAIN` prints

| GUC | Default | Effect on output |
|---|---|---|
| `explain_memory_verbosity` | `suppress` | `summary` adds `Vmem reserved:` to each slice line; `detail` gives every executor node its own memory context so `Executor Memory:` is printed for all of them. 7.x accepts only these three values — the 6.x-only `debug` (memory-account detail) was dropped from the enum, so `SET explain_memory_verbosity = 'debug'` errors on 7.x |
| `gp_enable_explain_allstat` | `off` | appends `allstat: seg_firststart_total_ntuples/seg0_…` per node — every segment's numbers, not just the maximum |
| `gp_explain_jit` | `on` | prints the `JIT:` summary block, per slice (tied to `COSTS`) |
| `optimizer_trace_fallback` | `off` | prints the `INFO`/`DETAIL` pair when GPORCA falls back |
| `optimizer_print_missing_stats` | `on` | raises `NOTICE: One or more columns in the following table(s) do not have statistics: …` |
| `gp_log_gang` | `off` | at `debug`, adds `gangN` to the slice annotation |

`EXPLAIN` options accepted on 7.x (`ExplainQuery()`): `ANALYZE`, `VERBOSE`, `COSTS`,
`SETTINGS`, `BUFFERS`, `TIMING`, `SUMMARY`, `FORMAT`, plus the Greengage-only `SLICETABLE`
and `DXL` — the last two are real options but are not in the `explain.sgml` synopsis.
6.x has neither `SETTINGS` nor `SUMMARY` nor `SLICETABLE`; its list is `ANALYZE`,
`VERBOSE`, `COSTS`, `BUFFERS`, `TIMING`, `FORMAT`, `DXL`. Only `ANALYZE` and `VERBOSE`, in
that order, may be written without parentheses.

See also: [../SKILL.md](../SKILL.md),
[../rules/plan-read-the-motions-first.md](../rules/plan-read-the-motions-first.md),
[../rules/plan-actual-rows-are-segment-max.md](../rules/plan-actual-rows-are-segment-max.md),
[../rules/plan-spill-lines-name-the-fix.md](../rules/plan-spill-lines-name-the-fix.md)
