---
description: Explain a Greengage query under both optimizers and interpret motions, slices and skew
argument-hint: "<query, file path, or description of the slow statement>"
---

Analyse the plan for: $ARGUMENTS

Load the **greengage-query-performance** skill — it owns how to read MPP plan output, and
this command is the driver, not the method.

## Procedure

1. **Get the statement.** If the user gave a file path or a description rather than SQL,
   find the actual statement first. Never analyse a paraphrase.

2. **Plan under both optimizers.** Greengage ships GPORCA and the PostgreSQL planner, and
   they produce different plans for the same query:

   ```sql
   SET optimizer = off;  EXPLAIN <query>;   -- PostgreSQL planner
   SET optimizer = on;   EXPLAIN <query>;   -- GPORCA
   ```

   Costs from the two are **not comparable** — never rank one against the other by cost.
   Check the optimizer line in the output: GPORCA falls back to the PostgreSQL planner
   silently, so `optimizer = on` does not guarantee you are looking at an ORCA plan.

3. **Measure, if it is safe to.** `EXPLAIN (ANALYZE, VERBOSE)` runs the query. Ask before
   running it against production or against anything that writes. On a read-only
   statement against a demo cluster, just run it.

4. **Read the plan for MPP-specific costs**, which is the whole point of this command:
   - **Motion nodes.** `Broadcast Motion` on a large table, or a `Redistribute Motion` that
     could have been avoided by co-locating the join keys, usually dominates everything
     else in the plan.
   - **Slices and gangs** — how many, and whether the slice count is proportional to what
     the query actually needs.
   - **Per-segment row counts** in `ANALYZE` output. Wildly uneven counts across segments
     mean skew, and the query runs at the speed of the slowest segment.
   - **Spill.** Work files and `Executor Memory` lines mean the operation exceeded its
     memory budget and went to disk.
   - Scans that read every partition where elimination was expected.

5. **Check the inputs to the plan** before blaming the planner: are statistics present and
   current (`gp_toolkit.gp_stats_missing`, last `ANALYZE`), and what is each table's
   distribution policy and storage type (`gp_distribution_policy`, `\d+`)? A bad plan is
   usually a symptom of a bad schema decision or missing statistics.

## Report

- The dominant cost, named specifically, with the plan lines that show it.
- Why it is happening, in terms of the MPP mechanism.
- The fix, ordered by leverage: statistics and query rewrite first (cheap, reversible),
  then distribution or storage changes (expensive, and a distribution change means
  rewriting the table).
- If a schema change is the real answer, say so plainly rather than proposing a query
  tweak that will not move the needle, and hand off to **greengage-schema-design**.
