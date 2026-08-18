---
description: Report Greengage cluster health - segment configuration, mirror sync, standby, disk, and skew
argument-hint: "[--deep]"
---

Produce a cluster health report for the Greengage cluster this session can reach.

Load the **greengage-cluster-ops** skill first — it owns the connection rules (which
environment to source, how to tell a demo cluster from a real one) and the correct
interpretation of every field below. Do not guess at the semantics; the skill has them.

## Collect

Establish a connection first, then gather:

1. **Version and topology**

   ```sql
   SELECT version();
   SELECT role, preferred_role, mode, status, count(*)
     FROM gp_segment_configuration
    GROUP BY 1,2,3,4 ORDER BY 1,2;
   ```

2. **Anything not healthy** — list these individually, they are the report's headline:

   ```sql
   SELECT dbid, content, role, preferred_role, mode, status, port, hostname, datadir
     FROM gp_segment_configuration
    WHERE status <> 'u' OR role <> preferred_role
    ORDER BY content, role;
   ```

3. **Standby coordinator replication** — `SELECT * FROM pg_stat_replication;` on the
   coordinator.

4. **Long-running and blocked activity** — `pg_stat_activity` ordered by
   `now() - query_start`, plus `gp_toolkit.gp_locks_on_relation` for anything waiting.

5. **Disk** — `gp_toolkit.gp_workfile_usage_per_segment` and
   `gp_toolkit.gp_workfile_mgr_used_diskspace` for spill pressure. If you have shell
   access to the hosts, `df -h` on the data directories.

6. **Missing statistics** — `SELECT * FROM gp_toolkit.gp_stats_missing;`

With `--deep`, additionally: `gp_toolkit.gp_skew_coefficients` and
`gp_toolkit.gp_skew_idle_fractions` (both scan every table — say so before running them on
a large cluster), `gp_toolkit.gp_bloat_diag`, and `gpstate -e` plus `gpstate -f` from the
shell if the `gp*` utilities are available.

## Report

Lead with a verdict — healthy, degraded, or broken — then the evidence. Call out
explicitly:

- Segments with `status = 'd'` (down), and segments where `role <> preferred_role` (failed
  over but not yet rebalanced). These are different problems with different fixes.
- Mirrors not in sync.
- **Do not report `mode = 'n'` on content `-1` as a problem.** That is the coordinator, and
  it is normal — its standby is tracked through `pg_stat_replication`, not through `mode`.

For each problem, name the specific next action (`gprecoverseg`, `gprecoverseg -r`,
`gpstart`, `ANALYZE`, …) and point at the skill section that covers it. Do not run any
recovery or DDL command yourself unless the user asks for it.
