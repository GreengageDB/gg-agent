# Workload-management monitoring views — exact columns per line

Column names differ between 6.x and 7.x on almost every resource-group view. A monitoring
query written against one line will not run against the other. Definitions read from
`gpcontrib/gp_toolkit/gp_toolkit--1.3.sql` (7.x — the newest base install script; a fresh
`CREATE EXTENSION` runs it and then the `1.3--1.4` … `1.8--1.9` upgrade scripts to reach
`default_version = '1.9'`) and `src/backend/catalog/gp_toolkit.sql` (6.x).

On 7.x `gp_toolkit` is an **extension** (`CREATE EXTENSION gp_toolkit`, schema
`gp_toolkit`); on 6.x it is loaded by `initdb` from a plain `.sql` file.

**Which views go empty when the manager is off.** The status views are backed by set-returning
functions that emit nothing unless their manager is active — `pg_resgroup_get_status()` returns
rows only `if (IsResGroupActivated())` (`resgroup_helper.c:235`) and `pg_resqueue_status_kv()`
only `if (IsResQueueEnabled())` (`resqueue.c:2245`). Under `gp_resource_manager = 'group'` the
in-tree test `resgroup_auxiliary_tools_v1.out` shows `pg_resqueue_status`,
`gp_toolkit.gp_resqueue_status` and `gp_toolkit.gp_resq_priority_backend` all at `(0 rows)`
while `gp_toolkit.gp_resgroup_config` lists all three groups. The catalog-join views
(`gp_resgroup_config`, `gp_resgroup_role`, `gp_resq_role`) always return rows.

## Resource group views

### `gp_toolkit.gp_resgroup_config` — configuration, never runtime

| 7.x columns | 6.x columns |
|---|---|
| `groupid`, `groupname`, `concurrency`, `cpu_max_percent`, `cpu_weight`, `cpuset`, `memory_limit`, `min_cost`, `io_limit` | `groupid`, `groupname`, `concurrency`, `cpu_rate_limit`, `memory_limit`, `memory_shared_quota`, `memory_spill_ratio`, `memory_auditor`, `cpuset` |

6.x decodes `memory_auditor` to the strings `vmtracker` / `cgroup` / `unknown`; 7.x has no
such column. Both are joins over `pg_resgroup` and `pg_resgroupcapability` — pure
configuration. Nothing here changes when the cluster is under load.

### `gp_toolkit.gp_resgroup_status` — the admission counters

| 7.x columns | 6.x columns |
|---|---|
| `groupid`, `groupname`, `num_running`, `num_queueing`, `num_queued`, `num_executed`, `total_queue_duration` | `rsgname`, `groupid`, `num_running`, `num_queueing`, `num_queued`, `num_executed`, `total_queue_duration`, `cpu_usage`, `memory_usage` |

7.x's view **projects a fixed column list** and therefore drops the `cpu_usage` /
`memory_usage` JSON that 6.x exposes via `SELECT r.rsgname, s.*`. Get per-host usage from
`gp_resgroup_status_per_host` instead. Note the name column is `groupname` on 7.x and
`rsgname` on 6.x.

Both are backed by `pg_resgroup_get_status(null)`, whose OUT parameters are
`groupid, num_running, num_queueing, num_queued, num_executed, total_queue_duration,
cpu_usage json, memory_usage json` (`pg_proc.dat` OID 6066).

| Column | Meaning |
|---|---|
| `num_running` | statements holding a slot right now |
| `num_queueing` | statements waiting for a slot **right now** — the number that matters |
| `num_queued` | cumulative count that has ever queued |
| `num_executed` | cumulative count admitted |
| `total_queue_duration` | cumulative `interval` spent waiting |

### `gp_toolkit.gp_resgroup_status_per_host`

| 7.x columns | 6.x columns |
|---|---|
| `groupid`, `groupname`, `hostname`, `cpu_usage`, `memory_usage` | `rsgname`, `groupid`, `hostname`, `cpu`, `memory_used`, `memory_available`, `memory_quota_used`, `memory_quota_available`, `memory_shared_used`, `memory_shared_available` |

6.x breaks memory into six columns because 6.x groups have a shared-quota/spill memory
model. 7.x has one `memory_usage` number. Both join
`gp_segment_configuration` on `role = 'p'`, so **mirrors are excluded** and the numbers are
primary-only.

### `gp_toolkit.gp_resgroup_status_per_segment`

| 7.x columns | 6.x columns |
|---|---|
| `groupid`, `groupname`, `segment_id`, `vmem_usage` | `rsgname`, `groupid`, `hostname`, `segment_id`, `cpu`, `memory_used`, `memory_available`, `memory_quota_used`, `memory_quota_available`, `memory_shared_used`, `memory_shared_available` |

7.x computes this from `gp_toolkit.resgroup_session_level_memory_consumption` (the vmem
tracker), **not** from `pg_resgroup_get_status`, so it reports vmem only and there is no
`hostname` column. 6.x's version joins `gp_segment_configuration` on `role = 'p'` and does
have `hostname`.

**Grant trap:** `GRANT SELECT ON gp_toolkit.gp_resgroup_status_per_segment TO public` is
added by the `gp_toolkit--1.8--1.9.sql` upgrade script, not by the base script. On a 7.x
cluster whose extension was never updated past 1.8, non-superusers get a permission error
on this one view while every sibling view works. Fix with
`ALTER EXTENSION gp_toolkit UPDATE TO '1.9';`.

### `gp_toolkit.resgroup_session_level_memory_consumption` — **7.x only**

`datname`, `sess_id`, `rsgid`, `rsgname`, `usename`, `query`, `segid`, `vmem_mb`,
`is_runaway`, `qe_count`, `active_qe_count`, `dirty_qe_count`, `runaway_vmem_mb`,
`runaway_command_cnt`, `idle_start`.

The only view that attributes memory to an individual session. `is_runaway = true` means
the runaway detector flagged it (`runaway_detector_activation_percent`).

**There is no `gp_toolkit.resgroup_session_level_memory_consumption` on 6.x.** The 6.x
equivalent is `session_state.session_level_memory_consumption`, created by
`CREATE EXTENSION gp_internal_tools` (`gpcontrib/gp_internal_tools/gp_internal_tools--1.0.0.sql:61`),
and it has **no `rsgid` / `rsgname` columns** — so on 6.x you cannot attribute session vmem
to a resource group from this view; join `pg_stat_activity` on `sess_id` instead.

### `gp_toolkit.gp_resgroup_role` — **7.x only**

`rrrolname`, `rrrsgname`. Inner join `pg_roles` × `pg_resgroup` on `rolresgroup`, so roles
with no assignment are **omitted**. There is no 6.x equivalent and no documentation page
(`/current/reference/gp_toolkit/gp_resgroup_role.html` returns 404). On 6.x, query
`pg_authid.rolresgroup` directly.

### `gp_toolkit.gp_resgroup_iostats_per_host` — **7.x only**

`rsgname`, `hostname`, `tablespace`, `rbps`, `wbps`, `riops`, `wiops`. Built on
`gp_toolkit.__gp_resgroup_iostats()`. Meaningful only under `gp_resource_manager = 'group-v2'`,
because io limits are a cgroup v2 feature.

## Resource queue views (identical on both lines except `gp_locks_on_resqueue`)

### `gp_toolkit.gp_resqueue_status`

`queueid`, `rsqname`, `rsqcountlimit`, `rsqcountvalue`, `rsqcostlimit`, `rsqcostvalue`,
`rsqmemorylimit`, `rsqmemoryvalue`, `rsqwaiters`, `rsqholders`.

Read as pairs: `rsqcountvalue` vs `rsqcountlimit` for `ACTIVE_STATEMENTS`, `rsqcostvalue`
vs `rsqcostlimit` for `MAX_COST`, `rsqmemoryvalue` vs `rsqmemorylimit` for `MEMORY_LIMIT`.
`rsqwaiters > 0` is the queue actually blocking someone.

Prefer this over the `pg_catalog.pg_resqueue_status` system view — the latter has no
memory columns (`rsqname`, `rsqcountlimit`, `rsqcountvalue`, `rsqcostlimit`, `rsqcostvalue`,
`rsqwaiters`, `rsqholders` only), which is exactly why the gp_toolkit version exists.

### `gp_toolkit.gp_resq_activity`

`resqprocpid`, `resqrole`, `resqoid`, `resqname`, `resqstart`, `resqstatus`.

`resqstatus` is derived: `'waiting'` when the underlying `pg_locks` row has
`granted = false`, otherwise `'running'`. Ordered by `resqstart`, so the top row is the
longest-waiting statement. Filters out `query = '<IDLE>'`.

### `gp_toolkit.gp_resq_activity_by_queue`

`resqoid`, `resqname`, `resqlast`, `resqstatus`, `resqtotal`. A `GROUP BY` rollup of the
above — one row per (queue, status).

### `gp_toolkit.gp_locks_on_resqueue`

| 7.x columns | 6.x columns |
|---|---|
| `lorusename`, `lorrsqname`, `lorlocktype`, `lorobjid`, `lortransaction`, `lorpid`, `lormode`, `lorgranted`, `lorwaitevent`, `lorwaiteventtype` | `lorusename`, `lorrsqname`, `lorlocktype`, `lorobjid`, `lortransaction`, `lorpid`, `lormode`, `lorgranted`, **`lorwaiting`** |

The last column is the only difference: 7.x exposes `pg_stat_activity.wait_event` /
`wait_event_type`, 6.x exposes the older boolean `waiting`.

The lowest-level view: it joins `pg_stat_activity` × `pg_locks` × `pg_resqueue`.
`lorgranted = false` is the definitive proof that a backend is parked on a queue rather
than on a table lock.

### `gp_toolkit.gp_resq_priority_backend` / `gp_resq_priority_statement`

`rqpsession`, `rqpcommand`, `rqppriority`, `rqpweight` — and the `_statement` view adds
`rqpdatname`, `rqpusename`, `rqpquery`.

**These describe CPU weighting, never admission.** A statement can show `rqppriority = MAX`
and still be waiting for a slot. Backed by `gp_list_backend_priorities()`.

### `gp_toolkit.gp_resq_role`

`rrrolname`, `rrrsqname`. LEFT JOIN, so roles with no queue appear with a NULL queue name —
the opposite of `gp_resgroup_role`, which inner-joins.

## `pg_stat_activity` — the fastest first look

| 7.x (PostgreSQL 12 base) | 6.x (PostgreSQL 9.4 base) |
|---|---|
| `wait_event_type`, `wait_event` | `waiting` (bool), `waiting_reason` (text) |
| `rsgid`, `rsgname` | `rsgid`, `rsgname`, `rsgqueueduration` |
| `sess_id`, `backend_type`, `state`, `query` | `sess_id`, `state`, `query` |

7.x `wait_event_type` values relevant here (`src/backend/postmaster/pgstat.c:3761`):
`ResourceGroup`, `ResourceQueue`. When `wait_event_type = 'ResourceGroup'`, `wait_event`
is replaced with **the name of the group being waited on**
(`src/backend/utils/adt/pgstatfuncs.c:719`) rather than a generic label — the group id is
an Oid and does not fit the uint16 wait-event id.

6.x `waiting_reason` values (`src/backend/utils/adt/pgstatfuncs.c:147`,
`src/include/pgstat.h:785`): `'lock'`, `'replication'`, `'resgroup'`. There is no
`'resqueue'` value: `resqueue.c:1298` calls `gpstat_report_waiting(PGBE_WAITING_LOCK)`, so
on 6.x a queue wait is indistinguishable from a table-lock wait in `pg_stat_activity`.
**`gp_toolkit.gp_locks_on_resqueue` is the only reliable queue-wait signal on 6.x.** 6.x
also has `rsgqueueduration`, which 7.x dropped.

```sql
-- 7.x
SELECT pid, sess_id, usename, rsgname, wait_event_type, wait_event, state,
       now() - query_start AS waited
FROM   pg_stat_activity WHERE state <> 'idle' ORDER BY query_start;

-- 6.x
SELECT pid, sess_id, usename, rsgname, waiting, waiting_reason,
       rsgqueueduration, state
FROM   pg_stat_activity WHERE state <> 'idle' ORDER BY query_start;
```

References:
[gp_toolkit overview](https://greengagedb.org/en/docs-gg/current/gp_toolkit.html) ·
[gp_resgroup_config](https://greengagedb.org/en/docs-gg/current/reference/gp_toolkit/gp_resgroup_config.html) ·
[gp_resgroup_status](https://greengagedb.org/en/docs-gg/current/reference/gp_toolkit/gp_resgroup_status.html) ·
[gp_resgroup_status_per_host](https://greengagedb.org/en/docs-gg/current/reference/gp_toolkit/gp_resgroup_status_per_host.html) ·
[gp_resgroup_status_per_segment](https://greengagedb.org/en/docs-gg/current/reference/gp_toolkit/gp_resgroup_status_per_segment.html) ·
[gp_resqueue_status](https://greengagedb.org/en/docs-gg/current/reference/gp_toolkit/gp_resqueue_status.html) ·
[gp_resq_activity](https://greengagedb.org/en/docs-gg/current/reference/gp_toolkit/gp_resq_activity.html) ·
[gp_resq_activity_by_queue](https://greengagedb.org/en/docs-gg/current/reference/gp_toolkit/gp_resq_activity_by_queue.html) ·
[gp_resq_priority_statement](https://greengagedb.org/en/docs-gg/current/reference/gp_toolkit/gp_resq_priority_statement.html) ·
[gp_resq_priority_backend](https://greengagedb.org/en/docs-gg/current/reference/gp_toolkit/gp_resq_priority_backend.html) ·
[gp_resq_role](https://greengagedb.org/en/docs-gg/current/reference/gp_toolkit/gp_resq_role.html) ·
[gp_locks_on_resqueue](https://greengagedb.org/en/docs-gg/current/reference/gp_toolkit/gp_locks_on_resqueue.html)
(these `/current/` pages document the 6.x column names; the 7.x columns above come from the source tree)
