---
title: Switch optimizers with SET in the session before changing the cluster default
impact: MEDIUM
impactDescription: "A cluster-wide optimizer change re-plans every query on the system; a per-session SET affects one workload and is reversible without a reload"
tags: [query-performance, optimizer, guc, operations]
---

## Switch optimizers with `SET` in the session before changing the cluster default

**Impact: MEDIUM**

`optimizer` is `PGC_USERSET`, so any role can change it for its own session with `SET`.
That is almost always the right scope: one report, one ETL step, one investigation. A
cluster-wide change with `gpconfig` re-plans every query on the system, including the ones
that were already fast, and needs `gpstop -u` to take effect.

Scope, cheapest first:

| Scope | How | Reversible by |
|---|---|---|
| One statement or block | `SET optimizer = off;` … `RESET optimizer;` | `RESET` |
| One session, from the client | `PGOPTIONS='-c optimizer=off' psql …` | ending the session |
| One function | `CREATE FUNCTION … SET optimizer = off AS …` | redefining the function |
| One role or one database | `ALTER ROLE etl SET optimizer = off;` / `ALTER DATABASE dw SET optimizer = off;` | `ALTER … RESET optimizer` |
| Whole cluster | `gpconfig -c optimizer -v off` then `gpstop -u` | `gpconfig -c optimizer -v on` then `gpstop -u` |

**Incorrect (cluster-wide change for one bad query):**

```sql
-- Bad: one slow report re-plans the entire workload.
\! gpconfig -c optimizer -v off
\! gpstop -u
```

**Correct (pin it at the narrowest scope that fixes the problem):**

```sql
-- Good: only this statement is affected, and the setting is explicitly undone.
SET optimizer = off;
SELECT c.region, sum(o.total)
FROM   orders o JOIN customers c USING (customer_id)
GROUP  BY c.region;
RESET optimizer;
```

```sql
-- Good: a whole ETL role that is known to hit GPORCA fallbacks anyway.
ALTER ROLE etl SET optimizer = off;
```

Two failure modes to recognise. If `SET optimizer` raises
`ERROR: cannot change the value of "optimizer"`, a superuser has set `optimizer_control =
off` — that GUC exists precisely to lock the choice down, and only a superuser can lift it.
If it raises `ORCA is not supported by this build`, the server was compiled
`--disable-orca` and `optimizer` can only ever be `off`.

Reference: [Server configuration parameters (GUCs) overview](https://greengagedb.org/en/docs-gg/current/reference/guc_reference.html)
