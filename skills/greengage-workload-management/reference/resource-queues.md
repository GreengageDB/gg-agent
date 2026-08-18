# Resource queues — attribute, catalog and error reference

Read from `refs/remotes/origin/7.x`. Resource queues are the older of the two systems and
are essentially identical on 6.x and 7.x; the deltas noted are the only ones found.

## Syntax

`doc/src/sgml/ref/create_resource_queue.sgml`, `alter_resource_queue.sgml`,
`drop_resource_queue.sgml`.

```sql
CREATE RESOURCE QUEUE name WITH (queue_attribute=value [, ...]);
-- A queue MUST have ACTIVE_STATEMENTS or MAX_COST (or both).

ALTER RESOURCE QUEUE name WITH    (queue_attribute=value [, ...]);
ALTER RESOURCE QUEUE name WITHOUT (queue_attribute [, ...]);   -- removes limits
DROP  RESOURCE QUEUE name [, ...];

CREATE ROLE r RESOURCE QUEUE q;
ALTER  ROLE r RESOURCE QUEUE {q | NONE};
```

`WITHOUT` takes bare attribute names and accepts `ACTIVE_STATEMENTS`, `MEMORY_LIMIT`,
`MAX_COST`, `COST_OVERCOMMIT`, `MIN_COST` — **not** `PRIORITY`, which gives
`ERROR: option "priority" cannot be disabled` (`pg_resourcetype.reshasdisable = 'f'`); an
unknown name gives `ERROR: option "<n>" is not a valid resource type`. Removing both
`ACTIVE_STATEMENTS` and `MAX_COST` leaves the queue in an invalid state; the reference page
says explicitly "Do not remove both these queue_attributes from a resource queue."

Only a superuser may create, alter or drop a resource queue (`must be superuser to
create/alter/drop resource queues`, `src/backend/commands/queue.c:727/1025/1421`). `ALTER` on
a queue that is currently in use is not permitted (`alter_resource_queue.sgml`, Notes).

When `gp_resource_manager` is not `queue`, `CREATE RESOURCE QUEUE` still succeeds — it writes
the catalog rows and emits `WARNING: resource queue is disabled` with the hint
`To enable set gp_resource_manager=queue` (`queue.c:957`). The queue enforces nothing.

## Attributes

| Attribute | Type | Default | Semantics |
|---|---|---|---|
| `ACTIVE_STATEMENTS` | integer > 0, or -1 | `-1` (no limit) | max concurrent statements from roles on the queue |
| `MAX_COST` | float, e.g. `3000.0` or `1e+2` | `-1` (no limit) | ceiling on the **sum** of admitted plan costs |
| `COST_OVERCOMMIT` | boolean | `FALSE` | `TRUE` lets an over-cost statement run when the queue is otherwise idle |
| `MIN_COST` | float | **`0`** — see below | plans below this are not queued at all |
| `PRIORITY` | `MIN\|LOW\|MEDIUM\|HIGH\|MAX` | `MEDIUM` | relative CPU share **after** admission |
| `MEMORY_LIMIT` | `'10MB'`, `'2GB'`, … | `-1` (no limit) | total memory for all the queue's statements on one segment host; minimum 10MB |

Cost is the planner's estimated total cost, in units of sequential disk page fetches —
the same number `EXPLAIN` prints. It is an estimate, so it moves with statistics and with
the choice of optimizer.

### The COST_OVERCOMMIT default is documented twice, differently

`create_resource_queue.sgml` prose says "the administrator can allow
`COST_OVERCOMMIT=TRUE` (the default)". Two paragraphs later the parameter list says "In the
default `COST_OVERCOMMIT=FALSE` case, such statements produce an error." The catalog seed
settles it:

- `src/include/catalog/pg_resqueue.dat` → `pg_default` has `rsqovercommit => 'f'`.
- `src/include/catalog/pg_resourcetype.dat` → `cost_overcommit` has
  `resdefaultsetting => '-1'`, `resdisabledsetting => '-1'`.

**Assume FALSE.** Set it explicitly in every `CREATE RESOURCE QUEUE` so the ambiguity
never reaches production.

`MIN_COST` has the same problem: `create_resource_queue.sgml` says "A value of -1.0 means
all queries are ignored. This is the default", and `pg_resourcetype.dat` gives `min_cost`
`resdefaultsetting => '-1'`. The observed value is 0 — `pg_resqueue.dat` seeds `pg_default`
with `rsqignorecostlimit => '0'`, and
`src/test/regress/expected/resource_queue.out` shows a freshly created
`CREATE RESOURCE QUEUE regressq ACTIVE THRESHOLD 1` landing on `rsqignorecostlimit = 0`.
**Assume 0**, i.e. nothing is exempt by default, and set `MIN_COST` explicitly if you want
small queries to skip the queue.

### Memory per query

From `create_resource_queue.sgml`:

| Queue shape | Per-query memory |
|---|---|
| statement-based | `MEMORY_LIMIT / ACTIVE_STATEMENTS` |
| cost-based | `MEMORY_LIMIT * (query_cost / MAX_COST)` |

The page recommends pairing `MEMORY_LIMIT` with `ACTIVE_STATEMENTS`, not with `MAX_COST`.
A session may override with `SET statement_mem`, bounded by `MEMORY_LIMIT` and
`max_statement_mem`. Summed `MEMORY_LIMIT` across all queues should not exceed a segment
host's physical memory; oversubscription is survivable only if workloads are staggered,
and queries are still cancelled when `gp_vmem_protect_limit` is exceeded.

## Catalogs

| Relation | OID | Columns |
|---|---|---|
| `pg_resqueue` | 6026 | `oid`, `rsqname`, `rsqcountlimit` (float4), `rsqcostlimit` (float4), `rsqovercommit` (bool), `rsqignorecostlimit` (float4) |
| `pg_resqueuecapability` | 6060 | `resqueueid`, `restypid` (int2, FK to `pg_resourcetype`), `ressetting` (text) — the attributes not stored in `pg_resqueue` |
| `pg_resourcetype` | 6059 | catalogue of the six attribute types and their defaults |
| `pg_authid.rolresqueue` | — | OID of the role's queue |

`pg_resourcetype` seed (`src/include/catalog/pg_resourcetype.dat`):

| OID | `resname` | `restypid` | `resdefaultsetting` | `resdisabledsetting` |
|---|---|---|---|---|
| 6454 | `active_statements` | 1 | `-1` | `-1` |
| 6455 | `max_cost` | 2 | `-1` | `-1` |
| 6456 | `min_cost` | 3 | `-1` | `0` |
| 6457 | `cost_overcommit` | 4 | `-1` | `-1` |
| 6458 | `priority` | 5 | `medium` | `_null_` |
| 6459 | `memory_limit` | 6 | `-1` | `-1` |

The single built-in queue is `pg_default`, OID 6055
(`ACTIVE_STATEMENTS=20`, `MAX_COST=-1`, `COST_OVERCOMMIT=false`, `MIN_COST=0`, from
`pg_resqueue.dat`; its only `pg_resqueuecapability` rows are `priority='medium'` and
`memory_limit='-1'`). Every role without an explicit `RESOURCE QUEUE` lands there —
`CreateRole` writes `DEFAULTRESQUEUE_OID` unconditionally (`user.c:566`).

`pg_resqueue` is `BKI_SHARED_RELATION`.

## Capacity GUCs

| GUC | Context | Default | Failure when exceeded |
|---|---|---|---|
| `max_resource_queues` | `PGC_POSTMASTER` | **9** | `insufficient resource queues available`, hint `Increase max_resource_queues` (`queue.c:952`) |
| `max_resource_portals_per_transaction` | `PGC_POSTMASTER` | 64 | `insufficient portal ids available`, hint `Increase max_resource_portals_per_transaction.` |
| `resource_scheduler` | `PGC_POSTMASTER` | `on` | queues silently do nothing when `off` |
| `resource_select_only` | `PGC_POSTMASTER` | `false` | when `on`, `INSERT`/`UPDATE`/`DELETE` are *not* queued; the default `off` queues them too |

`max_resource_queues` bounds `ResScheduler->num_queues`, which counts `pg_default` as well
(`ResCreateQueue`, `resscheduler.c:287`), so the default 9 leaves room for 8 queues of your
own — low enough that a normal per-team design hits it. Raising it requires a restart. The
same message with the hint `Increase max_resource_queues to <n>.` (`resscheduler.c:260`) is a
**PANIC at startup**, not the `CREATE` path.

## Error strings

`src/backend/utils/resscheduler/resqueue.c`, `resscheduler.c`.

| Error | Meaning |
|---|---|
| `statement requires more resources than resource queue allows` (`resqueue.c:499`), detail `resource queue id: <oid>, portal id: <n>` | Plan cost exceeds `MAX_COST` and `COST_OVERCOMMIT` is FALSE. The statement is **rejected**, not queued. |
| `deadlock detected, locking against self` (`resqueue.c:543`), detail `resource queue id: <oid>, portal id: <n>` | The session already holds slots on this queue and the new statement would have to wait on itself — e.g. an open cursor plus a query on a 1-statement queue (`ResCheckSelfDeadLock`) |
| `insufficient resource queues available` (`queue.c:952` on `CREATE`; `resscheduler.c:259` as a startup PANIC) | `max_resource_queues` reached |
| `Invalid parameter value "<v>" for resource type "MEMORY_LIMIT". Value must be at least 10240kB` (`queue.c:148`) | `MEMORY_LIMIT` below the 10 MB floor |
| `insufficient portal ids available` (`resscheduler.c:1044`) | `max_resource_portals_per_transaction` reached |
| `out of shared memory` + `You may need to increase max_resource_queues.` | resource-queue lock table full |
| `not enough shared memory for resource scheduler` (`resscheduler.c:154`) | startup sizing |

## What gets queued

Ordinary queries take the portal path in `PortalStart()`
(`src/backend/tcop/pquery.c:226`, and again at `:720` for the multi-query case):

```c
if (IsResQueueEnabled() && !superuser() && !IsResQueueLockedForPortal(portal))
    if ((!ResourceSelectOnly || portal->sourceTag == T_SelectStmt) && stmt->canSetTag)
        ResLockPortal(portal, queryDesc);
```

So `SELECT` is always subject to the queue, and `INSERT`/`UPDATE`/`DELETE` are too unless
`resource_select_only` is on. Utility statements go through
`ResHandleUtilityStmt()` (`src/backend/utils/resscheduler/resscheduler.c:1087`), which queues
one only when it is a `CopyStmt` or a `CreateTableAsStmt`, and only when
`Gp_role == GP_ROLE_DISPATCH && IsResQueueEnabled() && (!ResourceSelectOnly) && !superuser()`.
Other DDL is never queued.

**`!superuser()` on both paths means superusers bypass resource queues entirely** — confirmed
by [Use resource queues](https://greengagedb.org/en/docs-gg/current/resource_queues.html):
"Superuser queries are excluded from resource queue checks and always bypass queue
limitations." The same two `!superuser()` guards exist on 6.x (`pquery.c:281` and `:748`).

Statements whose plan cost is below the queue's `MIN_COST` are ignored for scheduling
purposes and run immediately.

There is no resource-queue equivalent of `gp_resource_group_queuing_timeout`. The wait is a
plain `ResProcSleep()` (`src/backend/storage/lmgr/proc.c:2123`) that arms `DEADLOCK_TIMEOUT`
and, when `LockTimeout > 0`, `LOCK_TIMEOUT` — so `SET lock_timeout` does bound it, and
`pg_cancel_backend(pid)` works through `CHECK_FOR_INTERRUPTS()`.

## Priority

`PRIORITY` is CPU weighting applied by a sweeper process after a statement has been
admitted. It never affects admission — a `PRIORITY=MAX` statement waits behind
`ACTIVE_STATEMENTS` exactly like any other.

| GUC | Context | Default |
|---|---|---|
| `gp_resqueue_priority` | `PGC_POSTMASTER` | `on` (variable `gp_enable_resqueue_priority`) |
| `gp_resqueue_priority_sweeper_interval` | `PGC_POSTMASTER` | 1000 ms (range 500–15000) |
| `gp_resqueue_priority_cpucores_per_segment` | `PGC_POSTMASTER` | 4.0 (range 0.1–512.0) |
| `gp_resqueue_priority_inactivity_timeout` | `PGC_POSTMASTER` | 2000 ms (range 500–INT_MAX) |
| `gp_resqueue_priority_default_value` | `PGC_POSTMASTER` | `MEDIUM` |
| `gp_resqueue_memory_policy` | `PGC_SUSET` | `NONE` (valid: `NONE`, `AUTO`, `EAGER_FREE`) |

Setting `gp_resource_manager` to `group` or `group-v2` forces
`gp_enable_resqueue_priority = false` (`src/backend/cdb/cdbvars.c:552`).

## In-tree tests

`make -C src/test/isolation2 installcheck-resource-queue` is a **7.x-only** target, and
7.x's isolation2 `installcheck` invokes it. 6.x's isolation2 `installcheck` has no
resource-queue target at all (`src/test/isolation2/Makefile:91`).
`gpcontrib/gp_toolkit` regression list includes `resource_manager_switch_to_queue` and
`resource_manager_restore_to_none`, which are the canonical switch procedures.

References:
[Use resource queues](https://greengagedb.org/en/docs-gg/current/resource_queues.html) ·
[CREATE RESOURCE QUEUE](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/create_resource_queue.html) ·
[ALTER RESOURCE QUEUE](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/alter_resource_queue.html) ·
[DROP RESOURCE QUEUE](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/drop_resource_queue.html) ·
[pg_resqueue](https://greengagedb.org/en/docs-gg/current/reference/pg_catalog/pg_resqueue.html) ·
[ALTER ROLE](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/alter_role.html)
