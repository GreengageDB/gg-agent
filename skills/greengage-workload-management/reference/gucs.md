# Workload-management GUCs

Every entry below is read from `src/backend/utils/misc/guc_gp.c` on
`refs/remotes/origin/7.x`, with 6.x checked where it differs. The **Context** column is the
`GucContext` in the GUC table and decides whether you can change it at all without a
restart:

| Context | How to change it |
|---|---|
| `PGC_POSTMASTER` | `gpconfig -c <name> -v <value>` then `gpstop -arf`. No `SET`, ever. |
| `PGC_SIGHUP` | `gpconfig` then `gpstop -u` (reload) |
| `PGC_SUSET` | `SET` as superuser, or `ALTER ROLE ... SET` |
| `PGC_USERSET` | `SET` in any session |

## Choosing and gating the manager

| GUC | Context | Default | Notes |
|---|---|---|---|
| `gp_resource_manager` | `PGC_POSTMASTER` | **`none`** (7.x) / `queue` (6.x) | `none`, `queue`, `group`, `group-v2` on 7.x; 6.x accepts only `queue` and `group` |
| `resource_scheduler` | `PGC_POSTMASTER` | `on` | ANDed into both `IsResQueueEnabled()` and `IsResGroupEnabled()`; `off` disables everything |
| `resource_select_only` | `PGC_POSTMASTER` | `false` | when on, only `SELECT` is subject to queues; at the default `off`, DML is queued too |
| `gp_resource_group_cgroup_parent` | `PGC_POSTMASTER`, `GUC_SUPERUSER_ONLY` | **`gpdb.service`** | cgroup directory the **backend** uses (`cgroup.c:177`); must match `^[0-9a-zA-Z][-._0-9a-zA-Z]*$`. `gpcheckresgroupimpl` / `gpcheckresgroupv2impl` ignore it and always check `gpdb` |

The `gp_resource_manager` check hook lives in `src/backend/cdb/cdbvars.c:526` and rejects
anything else with `invalid value for resource manager policy: "<v>"`. `gpconfig` adds its
own guard (`gpMgmt/bin/gpconfig:162`) that runs `gpcheckresgroupimpl` /
`gpcheckresgroupv2impl` on every host before accepting `group` / `group-v2`, and refuses
unknown values with `the value of gp_resource_manager must be 'none', 'queue', 'group', or 'group-v2'`.

## Resource groups

| GUC | Context | Default | Range | Notes |
|---|---|---|---|---|
| `gp_resource_group_cpu_limit` | `PGC_POSTMASTER` | `0.9` | 0.1–1.0 | fraction of host CPU the whole cluster may use |
| `gp_resource_group_cpu_priority` | `PGC_POSTMASTER` | `10` | 1–50 | CPU priority of postgres processes under resource groups |
| `gp_resource_group_queuing_timeout` | `PGC_USERSET` | **`0` = wait forever** | 0–INT_MAX ms | fires `canceling statement due to resource group waiting timeout` |
| `gp_resource_group_move_timeout` | `PGC_USERSET` | `30000` ms | 10–INT_MAX | how long `pg_resgroup_move_query` waits for the **target process** to take the slot over (`resGroupGiveSlotAway`); the wait for the slot itself uses `gp_resource_group_queuing_timeout` |
| `gp_resource_group_bypass` | `PGC_USERSET` | `false` | — | session opts out of its group; **cannot be set inside a transaction block** |
| `gp_resource_group_bypass_catalog_query` | `PGC_USERSET` | **`true`** | — | catalog-only plans skip the group |
| `gp_resource_group_bypass_direct_dispatch` | `PGC_USERSET` | **`true`** | — | direct-dispatch plans skip the group |
| `gp_resource_group_enable_alter_in_transaction` | `PGC_POSTMASTER` | `false` | — | allow `ALTER RESOURCE GROUP` inside a transaction block |
| `gp_resource_group_retrieve` | `PGC_SIGHUP` | `false` | — | when on, retrieve sessions of a parallel retrieve cursor share the declaring session's group and slots |
| `gp_resgroup_memory_policy` | `PGC_SUSET` | `EAGER_FREE` | `AUTO`, `EAGER_FREE` | operator memory distribution under groups |
| `gp_resgroup_memory_query_fixed_mem` | `PGC_USERSET` | `0` (kB) | 0–INT_MAX | non-zero **overrides the whole group memory calculation** for the session |
| `gp_resgroup_memory_policy_auto_fixed_mem` | `PGC_USERSET` | `100` kB | 50–INT_MAX | fixed memory for non-memory-intensive operators under `AUTO` |
| `gp_log_resgroup_memory` | `PGC_USERSET`, `GUC_NO_SHOW_ALL` | `false` | — | verbose group-memory logging |
| `gp_resgroup_debug_wait_queue` | `PGC_USERSET`, `DEVELOPER_OPTIONS` | `true` | — | wait-queue consistency checks; hidden from `SHOW ALL` |
| `debug_resource_group` | `PGC_USERSET`, `DEVELOPER_OPTIONS` | `false` | — | prints resource group debug logs |

**Two defaults to change on day one.** `gp_resource_group_queuing_timeout = 0` means a
saturated group hangs a session indefinitely — indistinguishable from a dead cluster. And
`gp_resource_group_bypass_catalog_query` / `..._bypass_direct_dispatch` default to `true`,
so a measurable slice of traffic never enters a group at all.

`SET gp_resource_group_bypass` inside a transaction is rejected by its check hook with
`SET gp_resource_group_bypass cannot run inside a transaction block`
(`guc_gp.c:5100`).

## Resource queues

| GUC | Context | Default | Range | Notes |
|---|---|---|---|---|
| `max_resource_queues` | `PGC_POSTMASTER` | **`9`** | 0–INT_MAX | counts `pg_default` too, so the 9th `CREATE RESOURCE QUEUE` fails |
| `max_resource_portals_per_transaction` | `PGC_POSTMASTER` | `64` | 0–INT_MAX | mislabelled "Maximum number of resource queues" in the GUC table |
| `gp_resqueue_priority` | `PGC_POSTMASTER` | `on` | — | C variable is `gp_enable_resqueue_priority`; force-cleared by group modes |
| `gp_resqueue_priority_sweeper_interval` | `PGC_POSTMASTER` | `1000` ms | 500–15000 | how often CPU shares are re-evaluated |
| `gp_resqueue_priority_inactivity_timeout` | `PGC_POSTMASTER` | `2000` ms | 500–INT_MAX | backend deemed inactive after this |
| `gp_resqueue_priority_cpucores_per_segment` | `PGC_POSTMASTER` | `4.0` | 0.1–512.0 | processing units per segment |
| `gp_resqueue_priority_default_value` | `PGC_POSTMASTER` | `MEDIUM` | MIN..MAX | weight when a statement has none |
| `gp_resqueue_memory_policy` | `PGC_SUSET` | `NONE` | `NONE`, `AUTO`, `EAGER_FREE` | note the different default from the resgroup twin |
| `gp_resqueue_memory_policy_auto_fixed_mem` | `PGC_USERSET` | `100` kB | 50–INT_MAX | fixed memory for light operators under `AUTO` |
| `gp_resqueue_print_operator_memory_limits` | `PGC_USERSET`, `GUC_NO_SHOW_ALL` | `false` | — | prints per-operator memory limits in `EXPLAIN` |
| `stats_queue_level` | `PGC_SUSET` | `false` | — | collect resource-queue-level statistics |

## Per-query memory (applies under both managers)

| GUC | Context | Default | Range |
|---|---|---|---|
| `statement_mem` | `PGC_USERSET` | `128000` kB | min 1000 kB (50 in assert-enabled builds) |
| `max_statement_mem` | `PGC_SUSET` | `2048000` kB (2 GB) | min 32768 kB |
| `gp_vmem_protect_limit` | `PGC_POSTMASTER` | `8192` MB | 0–INT_MAX/2 |
| `runaway_detector_activation_percent` | `PGC_POSTMASTER` | `90` | 0–100; `0` or `100` disables detection |

`statement_mem` is `PGC_USERSET`, so **any user can raise it**. Under resource groups it is
a floor, not a cap:

```c
/* src/backend/utils/resgroup/resgroup.c:3859, ResourceGroupGetQueryMemoryLimit() */
queryMem = (uint64)(resgLimit * 1024L * 1024L / caps->concurrency);
return Max(queryMem, stateMem);          /* stateMem = statement_mem * 1024 */
```

The only central bound is `max_statement_mem` (`PGC_SUSET`). Set it, and set
`gp_resgroup_memory_query_fixed_mem` nowhere — it short-circuits the group calculation
entirely when non-zero.

## Reading the running values

```sql
SELECT name, setting, unit, context, source
FROM   pg_settings
WHERE  name IN ('gp_resource_manager','resource_scheduler','statement_mem',
                'max_statement_mem','gp_vmem_protect_limit',
                'gp_resource_group_queuing_timeout','max_resource_queues',
                'gp_resource_group_bypass_catalog_query',
                'gp_resource_group_bypass_direct_dispatch',
                'gp_resource_group_cgroup_parent')
ORDER  BY name;
```

```bash
gpconfig -s gp_resource_manager     # shows coordinator and segment values separately
```

`gpconfig -s` is the one that catches a coordinator/segment mismatch — `SHOW` and
`pg_settings` only report the coordinator.

Reference:
[Server configuration parameters](https://greengagedb.org/en/docs-gg/current/reference/guc_reference.html) ·
[gpconfig](https://greengagedb.org/en/docs-gg/current/reference/utils/gpconfig.html) ·
[gpstop](https://greengagedb.org/en/docs-gg/current/reference/utils/gpstop.html) ·
[Spill files](https://greengagedb.org/en/docs-gg/current/spill_files.html)
(no `/7/` GUC page exists; `/current/` documents the 6.x set, and 7.x-only GUCs above come
from `src/backend/utils/misc/guc_gp.c`)
