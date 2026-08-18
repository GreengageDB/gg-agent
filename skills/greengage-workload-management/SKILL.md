---
name: greengage-workload-management
description: Controls Greengage cluster admission with resource groups or resource queues - gp_resource_manager none/queue/group/group-v2, cgroup v1/v2, CONCURRENCY, CPU_MAX_PERCENT, CPUSET, MEMORY_LIMIT, IO_LIMIT, ACTIVE_STATEMENTS, MAX_COST, PRIORITY, gp_toolkit views, statement_mem, superuser bypass. Use when a query hangs on wait_event_type='ResourceGroup', on "canceling statement due to resource group waiting timeout", "statement requires more resources than resource queue allows", or "cgroup is not properly configured".
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "7.x (6.x deltas noted)"
---

# Greengage workload management

Two mutually exclusive admission-control systems ship in the same binary. Everything you
tune belongs to exactly one of them, and picking the wrong one wastes days. Start here.

## There are four modes, not two, and 7.x defaults to none

`gp_resource_manager` is `PGC_POSTMASTER` (`src/backend/utils/misc/guc_gp.c:4624`).
Its check hook accepts exactly four strings on 7.x and only `queue`/`group` on 6.x
(`gpvars_check_gp_resource_manager_policy`, `cdbvars.c:526` / 6.x `cdbvars.c:669`):

| Value | What runs | Availability |
|---|---|---|
| `none` | **No admission control at all.** No queue, no group. | **7.x only**, and its default |
| `queue` | Resource queues (`pg_resqueue`, cost/statement admission) | both; 6.x **default** |
| `group` | Resource groups on **cgroup v1** | both |
| `group-v2` | Resource groups on **cgroup v2** | **7.x only** |

**The single most common wrong belief: "queues are the default".** They are on 6.x
(`guc_gp.c` default string `"queue"`). On 7.x the default is `"none"` — a fresh 7.x cluster
enforces nothing, yet `CREATE RESOURCE QUEUE` and `CREATE RESOURCE GROUP` still succeed and
their catalogs still fill up. Always confirm:

```sql
SHOW gp_resource_manager;   -- none | queue | group | group-v2
SHOW resource_scheduler;    -- must be on; both systems are gated on it
```

`resource_scheduler` (`PGC_POSTMASTER`, default `on`) gates both:
`IsResQueueEnabled()` and `IsResGroupEnabled()` both `AND` it in
`src/include/utils/resource_manager.h`. If it is `off`, nothing is enforced regardless of
`gp_resource_manager`.

## "Resource groups require cgroup v1" is a 6.x fact, not a 7.x fact

The published docs at
[Use resource groups](https://greengagedb.org/en/docs-gg/current/resource_groups.html)
say cgroup v1 — but `/current/` **is the Greengage 6 tree**, and that claim is true only
there. 7.x ships a complete v2 implementation:

| Evidence | 7.x | 6.x |
|---|---|---|
| `src/backend/utils/resgroup/cgroup-ops-linux-v2.c` | present | absent |
| `gpMgmt/bin/gpcheckresgroupv2impl` | present | absent |
| `make -C src/test/isolation2 installcheck-resgroup-v2` | present | absent |
| `gp_resource_manager = 'group-v2'` | accepted | rejected |

Detect what the host actually offers, then pick the matching mode:

```bash
stat -fc %T /sys/fs/cgroup/     # tmpfs => v1 hierarchy; cgroup2fs => unified v2
```

- `cgroup2fs` → use `group-v2` on 7.x. On 6.x this is fatal: boot with
  `systemd.unified_cgroup_hierarchy=0` and reboot to get v1 back.
- `tmpfs` → use `group`.

Validate before you restart anything. `gpconfig` runs the checker for you against every
host in `gp_segment_configuration` (`gpMgmt/bin/gppylib/gpresgroup.py`, `validate()` →
`gpcheckresgroupimpl`, `validate_v2()` → `gpcheckresgroupv2impl`), so a failure surfaces
as `gpconfig` refusing the value with `[<host>:cgroup is not properly configured: ...]`.

The exact files and permissions each checker demands are tabulated in
[reference/resource-groups.md](reference/resource-groups.md). One detail bites everyone:
**both checkers hard-code the directory name `gpdb`** and never read a GUC, while the backend
builds its paths from `gp_resource_group_cgroup_parent` (`cgroup.c:177`), whose default is
**`gpdb.service`**. `gpconfig` can pass on `/sys/fs/cgroup/gpdb/` while the server looks elsewhere.

## Switching managers is a restart, and none of the tuning carries over

Verbatim from the in-tree switch tests (`gpcontrib/gp_toolkit/sql/resource_manager_*.sql`,
`src/test/isolation2/sql/resgroup/resgroup_auxiliary_tools_v{1,2}.sql`):

```bash
gpconfig -c gp_resource_manager -v group-v2      # or group | queue | none (none is 7.x-only)
gpconfig -c gp_resource_group_cgroup_parent -v gpdb   # what the checkers look for; v2 hosts only
gpstop -arf                                      # -rai in the resgroup tests; both restart
```

Reconnect afterwards: the GUC is `PGC_POSTMASTER`, so an existing session keeps reporting
the old value. Switching to `group` or `group-v2` also force-clears `gp_resqueue_priority`
(`Gp_resource_manager_policy = ...GROUP; gp_enable_resqueue_priority = false;`,
`cdbvars.c:552`). Queue `PRIORITY` settings survive in `pg_resqueue`, silently do nothing,
and come back the moment you switch back. Do not read them as evidence of anything.

The concepts do not translate. `CPU_RATE_LIMIT` has no queue equivalent, `MAX_COST` has no
group equivalent, and a `MEMORY_LIMIT` means a **percentage** to 6.x groups, **megabytes**
to 7.x groups, and a **byte string like `'2GB'`** to queues. Do not port numbers across.

## Resource groups: the 7.x attribute set is not the one the docs show

`getResgroupOptionType()` (`src/backend/commands/resgroupcmds.c:965`) is the authority.
`doc/src/sgml/ref/create_resource_group.sgml` lags it — it omits three attributes the
parser accepts.

**7.x — verified accepted names, ranges from `checkResgroupCapLimit()`:**

| Attribute | Range | Default if omitted | Notes |
|---|---|---|---|
| `CONCURRENCY` | `[0, max_connections]` | 20 | 0 means the group admits nothing |
| `CPU_MAX_PERCENT` | `[1, 100]` or `-1` | **none — mandatory** | else `must specify cpu_max_percent or cpuset`; excludes `CPUSET` |
| `CPU_WEIGHT` | `[1, 500]` | 100 | relative share when groups compete |
| `CPUSET` | core list, e.g. `'0-3'` | `'-1'` (unset) | mutually exclusive with `CPU_MAX_PERCENT` |
| `MEMORY_LIMIT` | `[0, INT_MAX]` **MB** or `-1` | `-1` | `-1` = unlimited |
| `MIN_COST` | `[0, INT_MAX]` | **0** | plans cheaper than this bypass the group entirely |
| `IO_LIMIT` | tablespace io spec or `-1` | `'-1'` | **cgroup v2 only** |

**6.x is a different set entirely** — `CPU_RATE_LIMIT`, `MEMORY_LIMIT` (a percentage,
`[0,100]`), `MEMORY_SHARED_QUOTA`, `MEMORY_SPILL_RATIO`, `MEMORY_AUDITOR {vmtracker|cgroup}`,
`CONCURRENCY`, `CPUSET`. None of `CPU_MAX_PERCENT`, `CPU_WEIGHT`, `MIN_COST` or `IO_LIMIT`
exist there (`src/include/catalog/pg_resgroup.h`, `ResGroupLimitType`). Full side-by-side
tables, every error string, and the `CPUSET` / `IO_LIMIT` grammars are in
[reference/resource-groups.md](reference/resource-groups.md).

```sql
-- 7.x. Note: ALTER uses "SET <attr> <value>" with no equals sign and no parentheses.
CREATE RESOURCE GROUP etl_grp WITH (concurrency=4, cpu_max_percent=40, memory_limit=8192);
ALTER  RESOURCE GROUP etl_grp SET concurrency 8;
ALTER  RESOURCE GROUP etl_grp SET cpu_max_percent 60;
DROP   RESOURCE GROUP etl_grp;
```

`ALTER RESOURCE GROUP` inside a transaction block is rejected unless
`gp_resource_group_enable_alter_in_transaction` is on — and that GUC is `PGC_POSTMASTER`,
default `false`. `CREATE` and `DROP` are rejected in a transaction block unconditionally.

### Three built-in groups on 7.x, two on 6.x

`src/include/catalog/pg_resgroup.dat` seeds `default_group` (6437, concurrency 20,
cpu_max_percent 20), `admin_group` (6438, 10/10) and — **7.x only** — `system_group` (6441,
concurrency **0**, cpu_max_percent 10). All three get `cpu_weight=100`, `memory_limit=-1`,
`min_cost=500` (a catalog seed, not a default — a group you create gets 0), `io_limit=-1`.
6.x has only `default_group` (20 / cpu_rate_limit 30 / memory_limit 0) and `admin_group` (10/10/10).

### Role assignment, and the two groups you cannot assign

```sql
CREATE ROLE etl_user RESOURCE GROUP etl_grp;
ALTER  ROLE etl_user RESOURCE GROUP etl_grp;
ALTER  ROLE etl_user RESOURCE GROUP none;   -- rewrites the assignment, see below
SELECT * FROM gp_toolkit.gp_resgroup_role;  -- 7.x only: rrrolname, rrrsgname
```

`RESOURCE GROUP none` does not mean "unlimited". `ALTER ROLE ... RESOURCE GROUP none` writes
`admin_group` into `pg_authid.rolresgroup` for a superuser and `default_group` for everyone
else (`src/backend/commands/user.c:1293`), emitting a `NOTICE`; `CREATE ROLE` with no clause
does the same. `CREATE ROLE ... RESOURCE QUEUE none` is an error, not a reset. Refusals you
will hit (`src/test/isolation2/expected/resgroup/resgroup_syntax.out`):

| Statement | Error |
|---|---|
| non-superuser into `admin_group` | `only superuser can be assigned to admin resgroup` |
| any role into `system_group` | `assigning to system resgroup is not allowed` |
| `CREATE RESOURCE GROUP none ...` | `resource group name "none" is reserved` |
| `CPU_MAX_PERCENT` plus `CPUSET` | `can't specify both cpu_max_percent and cpuset` |
| two groups pinning the same core | `cpu cores 0 are used by resource group <name>` (a core the host lacks gives `cpu cores 1024 are unavailable on the system`) |

**A superuser created without a `RESOURCE GROUP` clause lands in `admin_group`** (`user.c:599`,
`NOTICE: resource group required -- using admin resource group "admin_group"`).

## Per-query memory: statement_mem is a floor, not a cap

This is the trap that makes group memory limits look broken.
`ResourceGroupGetQueryMemoryLimit()` (`src/backend/utils/resgroup/resgroup.c:3859`),
in order:

1. Query was bypassed (see below) → `statement_mem`.
2. `gp_resgroup_memory_query_fixed_mem > 0` → that value, full stop.
3. Group `memory_limit = -1` → `statement_mem`.
4. Otherwise `queryMem = memory_limit_MB * 1024 * 1024 / concurrency`, then
   **`return Max(queryMem, statement_mem)`**.

So a group with `memory_limit=1000, concurrency=2` gives 500 MB per query — *unless* the
user sets `statement_mem` higher, in which case the group limit is simply ignored. Cap it
centrally with `max_statement_mem` (`PGC_SUSET`, default 2048000 kB = 2 GB); `statement_mem`
itself defaults to 128000 kB and is `PGC_USERSET`, so any user can raise it.

Resource queues size memory the other way (from `create_resource_queue.sgml`):
statement-based queues give `MEMORY_LIMIT / ACTIVE_STATEMENTS` per query; cost-based queues
give `MEMORY_LIMIT * (query_cost / MAX_COST)`. Prefer `MEMORY_LIMIT` with
`ACTIVE_STATEMENTS`, not with `MAX_COST` — the reference page says so explicitly.

Neither system replaces `gp_vmem_protect_limit` (default 8192 MB per segment) or the
runaway detector (`runaway_detector_activation_percent`, default 90). A query inside its
group quota can still be killed by those.

## Queries that skip the group entirely

`check_and_unassign_from_resgroup()` (`resgroup.c:3911`) drops a query out of its group
before execution when any of these hold, and the query then runs on plain `statement_mem`:

| Condition | Controlled by | Default |
|---|---|---|
| Total plan cost `< min_cost` | group's `MIN_COST` | 0 for a group you created |
| Plan is direct-dispatch | `gp_resource_group_bypass_direct_dispatch` | **on** |
| Plan touches only catalogs | `gp_resource_group_bypass_catalog_query` | **on** |
| Session opted out — checked earlier, in `shouldBypassQuery()` (`resgroup.c:2815`) | `gp_resource_group_bypass` | off |

The first three never apply inside an explicit transaction block (`IsInTransactionBlock`).
The built-in groups carry `min_cost=500`, low enough that plenty of real work escapes them —
if concurrency limits are "not working", check the plan cost before blaming cgroups.

## Resource queues: cost admission blocks in ways nobody expects

Attributes accepted by `CREATE RESOURCE QUEUE` (`doc/src/sgml/ref/create_resource_queue.sgml`).
A queue must have `ACTIVE_STATEMENTS` **or** `MAX_COST`; both is allowed, neither is not.

| Attribute | Type | Default | Meaning |
|---|---|---|---|
| `ACTIVE_STATEMENTS` | integer | `-1` (no limit) | concurrent statements admitted |
| `MAX_COST` | float | `-1` (no limit) | sum of admitted plan costs (disk page fetches) |
| `COST_OVERCOMMIT` | bool | **`FALSE`** | over-cost statements run only when the queue is idle |
| `MIN_COST` | float | `0` | plans below this skip queueing entirely |
| `PRIORITY` | MIN/LOW/MEDIUM/HIGH/MAX | `MEDIUM` | CPU share, applied only after admission |
| `MEMORY_LIMIT` | `'10MB'`-style | `-1` | total memory for all statements from the queue, per segment host |

`COST_OVERCOMMIT`'s default is contradicted inside the SGML page itself. The catalog
settles it: `pg_resqueue.dat` seeds `pg_default` with `rsqovercommit => 'f'`, and
`pg_resourcetype.dat` gives `cost_overcommit` `resdefaultsetting => '-1'`. **Treat the
default as FALSE**, which means a single plan costing more than `MAX_COST` is rejected
outright, forever, with:

```
ERROR:  statement requires more resources than resource queue allows
DETAIL: resource queue id: <oid>, portal id: <n>
```

(`src/backend/utils/resscheduler/resqueue.c:499`.) That is the classic surprise: the query
is not slow and not waiting, it is *refused*, and the fix is a plan change, a higher
`MAX_COST`, or `COST_OVERCOMMIT=TRUE`. Because cost is the planner's estimate, a stale
`ANALYZE` can make a small query un-runnable — and GPORCA and the Postgres planner produce
non-comparable costs, so flipping `optimizer` changes admission.

```sql
CREATE RESOURCE QUEUE reporting WITH (ACTIVE_STATEMENTS=10, MEMORY_LIMIT='2GB', PRIORITY=LOW);
ALTER  RESOURCE QUEUE reporting WITH (ACTIVE_STATEMENTS=20);
ALTER  RESOURCE QUEUE reporting WITHOUT (MAX_COST, MEMORY_LIMIT);  -- WITHOUT removes limits
DROP   RESOURCE QUEUE reporting;
ALTER  ROLE analyst RESOURCE QUEUE reporting;
```

Every role lands in `pg_default` (OID 6055, `ACTIVE_STATEMENTS=20`, no cost limit) if you
never assign one. `max_resource_queues` (default **9**, `PGC_POSTMASTER`) counts *every* queue
including `pg_default`, so the default leaves room for 8 of your own; the next `CREATE` fails
with `insufficient resource queues available`, hint `Increase max_resource_queues` (`queue.c:952`).

**Superusers bypass resource queues completely.** The query path gates on
`IsResQueueEnabled() && !superuser()` (`src/backend/tcop/pquery.c:226`, same on 6.x), as does
the `COPY`/`CREATE TABLE AS` path (`resscheduler.c:1097`); the
[resource queues page](https://greengagedb.org/en/docs-gg/current/resource_queues.html) says so too. Testing a queue as `gpadmin` proves nothing.

## "My query is stuck" — three queries decide it

On **7.x**, `pg_stat_activity` carries `wait_event_type`, `wait_event`, `rsgid` and
`rsgname` (`src/backend/catalog/system_views.sql:743`), and the wait-event vocabulary
includes `ResourceGroup` and `ResourceQueue` (`src/backend/postmaster/pgstat.c:3761`).
For a `ResourceGroup` wait, `wait_event` is overwritten with **the resource group's name**
(`pgstatfuncs.c:719`) — not a generic label.

```sql
-- 1. Is workload management the cause at all?
SELECT pid, sess_id, usename, rsgname, wait_event_type, wait_event,
       state, now() - query_start AS waited, left(query, 60) AS q
FROM   pg_stat_activity
WHERE  state <> 'idle'
ORDER  BY query_start;
```

| `wait_event_type` | Verdict |
|---|---|
| `ResourceGroup` | Queued for a group slot. `wait_event` names the group. |
| `ResourceQueue` | Queued behind `ACTIVE_STATEMENTS` / `MAX_COST`. |
| `Lock` | **Not** workload management. A real lock wait — go to `pg_locks`. |
| `IPC`, `Timeout`, `IO` | Executing. Slow, not blocked. Wrong skill. |
| `NULL` and `state='active'` | Running on CPU. Wrong skill. |

```sql
-- 2a. Groups: is the group full, and how long has it been?
SELECT groupname, num_running, num_queueing, num_queued, num_executed, total_queue_duration
FROM   gp_toolkit.gp_resgroup_status ORDER BY num_queueing DESC;
SELECT groupname, concurrency, cpu_max_percent, cpu_weight, cpuset, memory_limit, min_cost, io_limit
FROM   gp_toolkit.gp_resgroup_config;
```

`num_queueing > 0` with `num_running = concurrency` is a saturated group: raise
`CONCURRENCY`, or move the query (below). `num_running < concurrency` while sessions still
wait means the wait is somewhere else.

```sql
-- 2b. Queues: holders vs waiters, and which limit is binding.
SELECT rsqname, rsqcountlimit, rsqcountvalue, rsqcostlimit, rsqcostvalue,
       rsqmemorylimit, rsqmemoryvalue, rsqwaiters, rsqholders
FROM   gp_toolkit.gp_resqueue_status;

SELECT resqname, resqrole, resqstatus, resqstart FROM gp_toolkit.gp_resq_activity;
SELECT resqname, resqstatus, resqtotal, resqlast FROM gp_toolkit.gp_resq_activity_by_queue;
SELECT lorusename, lorrsqname, lorgranted, lorwaitevent FROM gp_toolkit.gp_locks_on_resqueue;
```

`rsqcountvalue >= rsqcountlimit` → `ACTIVE_STATEMENTS` is binding.
`rsqcostvalue >= rsqcostlimit` → `MAX_COST` is binding.
`gp_locks_on_resqueue` with `lorgranted = false` is the definitive "this backend is parked
on the queue" signal.

```sql
-- 3. Rule out a degraded cluster before touching any limit.
SELECT content, role, preferred_role, mode, status FROM gp_segment_configuration
WHERE  status <> 'u' OR role <> preferred_role;
```

Empty result = healthy. `mode='n'` on content `-1` is normal, not a fault. If this returns
rows the queue depth is a symptom, not the disease — see
[greengage-cluster-ops](../greengage-cluster-ops/SKILL.md).

**Noise to ignore while diagnosing.** `gp_resq_priority_backend` / `gp_resq_priority_statement`
show CPU weights, never admission — a query at `PRIORITY=MAX` can still be queued.
`gp_toolkit.gp_resgroup_config` is pure configuration: it lists all three built-in groups even
under `gp_resource_manager = none`. But `gp_resqueue_status` and `gp_resgroup_status` return
**zero rows** unless their manager is active — an empty status view is proof, not a bug.

### Timeouts

`gp_resource_group_queuing_timeout` is `PGC_USERSET` and **defaults to 0 = wait forever**.
`SET gp_resource_group_queuing_timeout = '30s';` turns a saturated group into a bounded
`ERROR: canceling statement due to resource group waiting timeout` instead of a hang.
Resource queues have no timeout GUC of their own, but the wait is an ordinary `ProcSleep`
that honours `lock_timeout` (`ResProcSleep()`, `proc.c:2123`); `pg_cancel_backend(pid)` also works.

## Moving a running query between groups

7.x only, and the signature differs from 6.x in both schema and argument:

```sql
-- 7.x: pg_catalog, takes a PID, superuser only.
SELECT pg_resgroup_move_query(pid, 'admin_group')
FROM   pg_stat_activity WHERE rsgname = 'etl_grp' AND state = 'active';
```

```sql
-- 6.x: gp_toolkit schema, takes a SESSION ID (sess_id), not a pid.
SELECT gp_toolkit.pg_resgroup_move_query(sess_id, 'admin_group')
FROM   pg_stat_activity WHERE rsgname = 'etl_grp';
```

Passing a pid to the 6.x form addresses a different session or none at all. The move is
refused for an idle session (`process <pid> is in IDLE state`), a bypassed session
(`cannot move a process from bypassed group`), a non-superuser caller
(`must be superuser to move query`), a `system_group` destination, and while any
`ALTER RESOURCE GROUP` transaction is open (`cannot move query while a resource group is
being edited`). The full list with the memory-shortfall errors is in
[reference/resource-groups.md](reference/resource-groups.md).

You cannot move a session that is itself queued (`wait_event_type='ResourceGroup'`): it holds
no group yet, so the call fails with `process <pid> is in IDLE state`. The caller acquires a
slot in the destination group and may queue for one — bounded by `gp_resource_group_queuing_timeout`,
not by `gp_resource_group_move_timeout` (30000 ms), which covers only the hand-over to the target.

## What not to do

- **Never set `gp_resource_manager` with `SET` or in a session.** It is `PGC_POSTMASTER`.
  `gpconfig` + `gpstop -arf`, always.
- **Never run `gpconfig -c gp_resource_manager -v group` without checking cgroups first.**
  `gpconfig` validates, but a hand-edited `postgresql.conf` does not, and the cluster then
  fails to start correctly.
- **Never assume `IO_LIMIT` did anything under `group`.** Under cgroup v1 it emits
  `WARNING: resource group io limit only can be used in cgroup v2.`
  (`cgroup-ops-linux-v1.c:1178`) and returns — a warning, not an error, so scripts pass.
- **Never trust the `CPUSET='<a>;<b>'` ordering from the docs without verifying.** The docs
  say `'<master_cores>;<segment_cores>'`, but `getCpuSetByRole()`
  (`resgroupcmds.c:2126`; same logic at 6.x `resgroupcmds.c:1831`) hands the part *after* the `;` to
  `IS_QUERY_DISPATCHER()`. Set it, then read back `gp_toolkit.gp_resgroup_config` and the
  cgroup `cpuset.cpus` files before you rely on the split.
- **Never tune both systems.** Objects for the inactive one still create, alter and appear
  in `gp_toolkit` while enforcing nothing.
- **Never benchmark limits as a superuser.** Queues skip superusers entirely; unassigned
  superusers land in `admin_group`.
- **Never leave `gp_resource_group_queuing_timeout` at 0 in production.** Zero is an
  unbounded hang that looks exactly like a hung cluster.

Reference: [resource-groups](reference/resource-groups.md) ·
[resource-queues](reference/resource-queues.md) ·
[monitoring-views](reference/monitoring-views.md) · [gucs](reference/gucs.md)

See also: [greengage-cluster-ops](../greengage-cluster-ops/SKILL.md),
[greengage-query-performance](../greengage-query-performance/SKILL.md),
[greengage-debug](../greengage-debug/SKILL.md),
[greengage-overview](../greengage-overview/SKILL.md),
[greengage-internals](../greengage-internals/SKILL.md),
[greengage-testing](../greengage-testing/SKILL.md)
