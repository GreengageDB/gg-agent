---
title: Raise statement_mem in the session, never in postgresql.conf
impact: MEDIUM-HIGH
impactDescription: "statement_mem is charged per statement per segment, so a cluster-wide raise multiplies by segments times concurrency and is how a cluster starts running out of memory"
tags: [query-performance, memory, statement-mem, operations]
---

## Raise `statement_mem` in the session, never in `postgresql.conf`

**Impact: MEDIUM-HIGH**

`statement_mem` is the memory budget one statement receives **on each segment**. Multiply
it out before changing it: on a 24-segment cluster with 40 concurrent statements, a value
of 1900 MB is a 1.7 TB promise. The GUC is `PGC_USERSET` precisely so that the one query
that needs a lot can ask for a lot without every other query on the system doing the same.

The guard rails, all verifiable with `SHOW`:

| GUC | Default | Scope | Role |
|---|---|---|---|
| `statement_mem` | `128000` kB (125 MB) | `USERSET` | per statement, per segment |
| `max_statement_mem` | `2048000` kB (2000 MB) | `SUSET` | ceiling on `statement_mem`; a `SET` at or above it is **rejected**, not clamped |
| `gp_vmem_protect_limit` | `8192` MB | `POSTMASTER` | total virtual memory one segment may use across all its processes |
| `runaway_detector_activation_percent` | `90` | `POSTMASTER` | percentage of the vmem quota at which the runaway detector starts cancelling the biggest consumer; `0` or `100` disables it |

Exceed `gp_vmem_protect_limit` and the runaway detector cancels sessions with
`ERROR: Canceling query because of high VMEM usage. Used: <N>MB, available <N>MB, red
zone: <N>MB` (`src/backend/utils/mmgr/runaway_cleaner.c`). That message means the *segment*
ran out, not your statement — raising `statement_mem` further makes it more likely, not
less.

**Incorrect (a cluster-wide raise to fix one report):**

```bash
# Bad: every statement on every segment now reserves 1900MB. (A value at or
# above max_statement_mem is rejected, so this is close to the largest cluster
# -wide mistake you can make without also raising the ceiling.)
gpconfig -c statement_mem -v 1900MB
gpstop -u
```

**Correct (raise it for the statement that needs it, then put it back):**

```sql
-- Good: scoped to this session, and explicitly reset.
SET statement_mem = '420MB';
SELECT customer_id, count(*) FROM orders GROUP BY customer_id;
RESET statement_mem;
```

```sql
-- Good: a whole ETL role that is known to run large sorts, bounded by
-- max_statement_mem and by how many such sessions you allow.
ALTER ROLE etl SET statement_mem = '1GB';
```

```bash
# Good: one client session, without touching server config.
PGOPTIONS="-c statement_mem=420MB" psql -d dw -f nightly_rollup.sql
```

Check what is actually in force, and what the ceiling is, before concluding a raise did
nothing:

```sql
SELECT name, setting, unit, source, context
FROM   pg_settings
WHERE  name IN ('statement_mem', 'max_statement_mem', 'gp_vmem_protect_limit');
```

`max_statement_mem` is `SUSET`, so a non-superuser cannot lift its own ceiling; when
`SET statement_mem` fails with
`ERROR: Invalid input for statement_mem, must be less than max_statement_mem (2048000 kB)`
(`gpvars_check_statement_mem()`), that is why. On 6.x with resource groups,
`memory_spill_ratio` additionally controls the point at which a query starts spilling; that
GUC does not exist on 7.x.

Reference: [How to manage spill files](https://greengagedb.org/en/docs-gg/current/spill_files.html)
