# Resource groups — attribute, catalog and error reference

Everything here is read from `refs/remotes/origin/7.x` and `refs/remotes/origin/6.x` of
`GreengageDB/greengage`. Where the shipped SGML page disagrees with the parser, the parser
wins and the disagreement is called out.

## Attribute names the parser accepts

`getResgroupOptionType()` — `src/backend/commands/resgroupcmds.c:965` (7.x).
`ResGroupLimitType` — `src/include/catalog/pg_resgroup.h`.

| `reslimittype` | 7.x name | 6.x name |
|---|---|---|
| 1 | `concurrency` | `concurrency` |
| 2 | `cpu_max_percent` | `cpu_rate_limit` |
| 3 | `cpu_weight` | `memory_limit` |
| 4 | `cpuset` | `memory_shared_quota` |
| 5 | `memory_limit` | `memory_spill_ratio` |
| 6 | `min_cost` | `memory_auditor` |
| 7 | `io_limit` | `cpuset` |

**The numeric `reslimittype` means something different on each line.** Any query that
joins `pg_resgroupcapability` on a hard-coded `reslimittype` is version-specific. Use
`gp_toolkit.gp_resgroup_config` instead.

`doc/src/sgml/ref/create_resource_group.sgml` on 7.x lists only
`CPU_MAX_PERCENT | CPUSET`, `CONCURRENCY`, `CPU_WEIGHT`. It omits `MEMORY_LIMIT`,
`MIN_COST` and `IO_LIMIT`, all of which the parser accepts and the isolation2 tests
exercise (`src/test/isolation2/sql/resgroup/resgroup_syntax.sql`,
`resgroup_memory_limit.sql`).

## 7.x limits and defaults

Ranges from `checkResgroupCapLimit()` and the `#define`s at the top of
`src/backend/commands/resgroupcmds.c`.

| Attribute | Min | Max | Disabled value | Constant |
|---|---|---|---|---|
| `CONCURRENCY` | 0 | `max_connections` | — | `RESGROUP_MIN/MAX_CONCURRENCY` |
| `CPU_MAX_PERCENT` | 1 | 100 | `-1` | `CPU_MAX_PERCENT_DISABLED` (`utils/cgroup.h:45`) |
| `CPU_WEIGHT` | 1 | 500 | — | `RESGROUP_MIN/MAX_CPU_WEIGHT` |
| `MEMORY_LIMIT` (MB) | 0 | `INT_MAX` | `-1` | `RESGROUP_DEFAULT_MEMORY_LIMIT` |
| `MIN_COST` | 0 | `INT_MAX` (`capability min_cost is out of range` beyond) | — | `RESGROUP_MIN_MIN_COST` |
| `CPUSET` | — | 1024 chars | `'-1'` | `MaxCpuSetLength`, `DefaultCpuset` |
| `IO_LIMIT` | 2 | per-key max | `'-1'` | `DefaultIOLimit` |

`MaxResourceGroups` is 100 (`src/include/utils/resgroup.h`).

**Defaults for a group you create** (`parseStmtOptions`, `resgroupcmds.c:1186`–`1194`) are
*not* the values seeded for the built-in groups: `concurrency` 20, `cpu_weight` 100,
`memory_limit` `-1`, `min_cost` **0**. One of `CPU_MAX_PERCENT` / `CPUSET` is **mandatory** —
omitting both gives `ERROR: must specify cpu_max_percent or cpuset` (`resgroupcmds.c:1185`). `CREATE`, `ALTER`
and `DROP RESOURCE GROUP` all require superuser (`resgroupcmds.c:127`, `:411`, `:293`).

## What `gpcheckresgroupimpl` / `gpcheckresgroupv2impl` validate

Both binaries live in `gpMgmt/bin/`. `gpconfig` runs them on every host in
`gp_segment_configuration` before it accepts `gp_resource_manager = group` or `group-v2`
(`gpMgmt/bin/gppylib/gpresgroup.py`, `validate()` / `validate_v2()`). A failure surfaces as
`[<host>:cgroup is not properly configured: <detail>]` — the format string is
`"[{}:{}]".format(remoteHost, stderr)`, with no space after the colon.

Paths are relative to the cgroup mount point discovered from `/proc/self/mounts`. **The
directory name `gpdb` below is hard-coded in both scripts** — neither reads
`gp_resource_group_cgroup_parent`, whose GUC default is `gpdb.service` and which *is* what
the backend uses (`src/backend/utils/resgroup/cgroup.c:177`). A cluster left on the GUC
default therefore passes a check against a directory the server will not use.

| v1 — `gpcheckresgroupimpl` | v2 — `gpcheckresgroupv2impl` (7.x only) |
|---|---|
| `cpu/gpdb/` rwx | `cgroup.procs` rw, `gpdb/` rwx |
| `cpu/gpdb/{cgroup.procs,cpu.cfs_period_us,cpu.cfs_quota_us,cpu.shares}` rw | `gpdb/{cgroup.procs,cpu.max,cpu.weight,cpu.weight.nice}` rw |
| `cpuacct/gpdb/` rwx, `cpuacct/gpdb/cgroup.procs` rw | `gpdb/cpu.stat` r |
| `cpuacct/gpdb/{cpuacct.usage,cpuacct.stat}` r | `gpdb/{cpuset.cpus,cpuset.cpus.partition,cpuset.mems}` rw |
| `cpuset/gpdb/` rwx, `cpuset/gpdb/cgroup.procs` rw | `gpdb/{cpuset.cpus.effective,cpuset.mems.effective}` r |
| `cpuset/gpdb/{cpuset.cpus,cpuset.mems}` rw | `gpdb/memory.current` r |
| `memory/gpdb/` rwx, `memory/gpdb/cgroup.procs` rw | `gpdb/io.max` rw |
| `memory/gpdb/memory.usage_in_bytes` r | — |

v1 additionally refuses a host where `cpu` and `cpuset` are mounted on the same hierarchy
(`can't mount 'cpu' and 'cpuset' on the same hierarchy`, from `/proc/1/cgroup`).

Both scripts carry the comment "The checks should keep in sync with
`src/backend/utils/resgroup/cgroup-ops-v1.c` / `-v2.c`" — if a check fails, that C file
says what the backend will do with the file.

On a **non-Linux** platform (`sys.platform` does not start with `linux`),
`gpcheckresgroupimpl` falls back to a `Dummy` class that exits with
`resource group is not supported on this platform`. `gpcheckresgroupv2impl` has no such
fallback.

Separately, `gpconfig -c gp_resource_group_cgroup_parent -v <name>` only works on a cgroup
**v2** host: its guard scans `psutil.disk_partitions` for an `fstype == "cgroup2"` mount and
otherwise fails with `cannot find cgroup v2 mountpoint`; it also requires the directory to
already exist (`gpMgmt/bin/gpconfig:173`).

## Built-in groups

`src/include/catalog/pg_resgroup.dat` + `pg_resgroupcapability.dat` (7.x):

| Group | OID | concurrency | cpu_max_percent | cpu_weight | cpuset | memory_limit | min_cost | io_limit |
|---|---|---|---|---|---|---|---|---|
| `default_group` | 6437 | 20 | 20 | 100 | -1 | -1 | 500 | -1 |
| `admin_group` | 6438 | 10 | 10 | 100 | -1 | -1 | 500 | -1 |
| `system_group` | 6441 | 0 | 10 | 100 | -1 | -1 | 500 | -1 |

`src/include/catalog/pg_resgroup.h` + `pg_resgroupcapability.h` (6.x) — **no
`system_group`**:

| Group | OID | concurrency | cpu_rate_limit | memory_limit | memory_shared_quota | memory_spill_ratio | memory_auditor | cpuset |
|---|---|---|---|---|---|---|---|---|
| `default_group` | 6437 | 20 | 30 | 0 | 80 | 0 | 0 (`vmtracker`) | -1 |
| `admin_group` | 6438 | 10 | 10 | 10 | 80 | 0 | 0 (`vmtracker`) | -1 |

## Catalogs

| Relation | OID | Columns |
|---|---|---|
| `pg_resgroup` | 6436 | `oid`, `rsgname`, `parent` |
| `pg_resgroupcapability` | 6439 | `resgroupid`, `reslimittype` (int2), `value` (text) |
| `pg_authid.rolresgroup` | — | OID of the role's group; 0 only for the bootstrap roles |

Both `pg_resgroup` and `pg_resgroupcapability` are `BKI_SHARED_RELATION` — cluster-wide,
not per-database.

`CreateRole` always writes a `rolresgroup` (explicit group, else `admin_group` for a
superuser, else `default_group` — `user.c:574`–`618`), so 0 appears only for the roles
seeded by `pg_authid.dat`, which initdb never assigns a group to. For those,
`decideResGroup()` finds no group in the shared hash and falls back to
`superuser() ? ADMINRESGROUP_OID : DEFAULTRESGROUP_OID` (`resgroup.c:1294`) — which is why
the bootstrap superuser (`gpadmin`) runs in `admin_group` with nothing in `pg_authid` to
show for it.

## Syntax

```sql
-- 7.x
CREATE RESOURCE GROUP name WITH (attr=value [, ...]);
ALTER  RESOURCE GROUP name SET attr value;     -- no '=', no parentheses
DROP   RESOURCE GROUP name;

CREATE ROLE r RESOURCE GROUP g;
ALTER  ROLE r RESOURCE GROUP {g | none};
```

`ALTER` takes exactly one attribute per statement (`alter_resource_group.sgml`:
`ALTER RESOURCE GROUP name SET group_attribute value`).

### CPUSET grammar

`checkCpuSetByRole()` (`resgroupcmds.c:2075`) splits on the `;` and hands each half to
`checkCpusetSyntax()`; `getCpuSetByRole()` (`resgroupcmds.c:2126`) picks the half to use.

- A core list: `'0'`, `'0-3'`, `'0,2,4'`, `'0-2,7'`.
- Optionally split by a single `;` into two lists, one for the coordinator and one for the
  segments: `'0-1;2-7'`.
- `CPUSET` and `CPU_MAX_PERCENT` are mutually exclusive. Setting `CPUSET` forces
  `cpuMaxPercent = CPU_MAX_PERCENT_DISABLED` and `cpuWeight = 100`
  (`resgroupcmds.c`, `parseStmtOptions`).
- Cores may not overlap between groups.

**Ordering caveat.** The 6.x documentation page renders this as
`CPUSET='<master_cores>;<segment_cores>'`, and the in-code comment above
`getCpuSetByRole()` says "assign '1' to coordinator and '4' to segment" for `'1;4'`. The
code does the opposite: `if (IS_QUERY_DISPATCHER()) splitcpuset = scpu;` hands the part
**after** the `;` to the dispatcher. 6.x has the same logic (`resgroupcmds.c:1831`), so this
is long-standing, not a 7.x regression. Set it, then verify against
`gp_toolkit.gp_resgroup_config` and the actual `cpuset.cpus` files before relying on the
order.

### IO_LIMIT grammar (7.x, cgroup v2 only)

`src/backend/utils/resgroup/io_limit_gram.y`, `io_limit_scanner.l`,
`src/include/utils/cgroup_io_limit.h`.

```
io_limit := <tablespace>:<key>=<value>[,<key>=<value>...][;<tablespace>:...]
<tablespace> := tablespace name | tablespace OID | '*'
<key>        := rbps | wbps | riops | wiops
<value>      := integer in [2, max_for_key] | the literal 'max'
```

**`rbps`/`wbps` are megabytes per second, not bytes** — `setio_v2()` writes
`rbps=<value> * 1024 * 1024` into the cgroup v2 `io.max` file
(`cgroup-ops-linux-v2.c:862`), one line per backing device (`<major>:<minor> rbps=… wbps=…
riops=… wiops=…`). `riops`/`wiops` are passed through unscaled. Per-key maxima come from
`io_limit_value_validate()` (`cgroup_io_limit.c:311`): `ULLONG_MAX/1024/1024` for the bps
keys, `UINT_MAX` for the iops keys; below 2 is rejected with
`value of '<key>' must in range [2, <max>] or equal 'max'`. `*` means all tablespaces and
cannot be combined with a named one (`tablespace '*' cannot be used with other tablespaces`).
Using `IO_LIMIT` while `cgroupOpsRoutine` is unset gives
`resource group must be enabled to use io limit feature`.

Under `gp_resource_manager = 'group'` (v1) every io_limit entry point is a stub that emits
`WARNING: resource group io limit only can be used in cgroup v2.` and returns
(`cgroup-ops-linux-v1.c:1178`, `parseio_v1`/`setio_v1`/`freeio_v1`/`getiostat_v1`/`dumpio_v1`/`cleario_v1`).
It is a warning, so `CREATE RESOURCE GROUP` still succeeds and the limit is silently inert.

## Error strings

From `src/test/isolation2/expected/resgroup/resgroup_syntax.out` and
`.../resgroup_move_query.out`, plus the `ereport` sites they come from.

| Error | Cause |
|---|---|
| `resource group "<n>" does not exist` | unknown group in `ALTER ROLE` / `DROP` |
| `resource group "<n>" already exists` | `CREATE` over a built-in or existing group |
| `resource group name "none" is reserved` | `CREATE RESOURCE GROUP none` |
| `only superuser can be assigned to admin resgroup` | non-superuser → `admin_group` |
| `assigning to system resgroup is not allowed` | any role → `system_group` |
| `found duplicate resource group resource type: <attr>` | attribute listed twice in one `WITH` |
| `option "<name>" not recognized` | attribute name not in `getResgroupOptionType` |
| `can't specify both cpu_max_percent and cpuset` | mutual exclusion |
| `cpuset invalid` | `checkCpusetSyntax` rejection |
| `must specify cpu_max_percent or cpuset` | `CREATE` with neither (`resgroupcmds.c:1185`) |
| `cpu cores <n> are unavailable on the system` | the host has no such core (`resgroupcmds.c:1850`) |
| `cpu cores <n> are used by resource group <name>` | the core is already pinned by another group (`resgroupcmds.c:1918`) |
| `the length of cpuset reached the upper limit 1024` | `MaxCpuSetLength` |
| `concurrency range is [0, 'max_connections']` | out-of-range `CONCURRENCY` |
| `cpu_max_percent range is [1, 100] or equals to -1` | out-of-range `CPU_MAX_PERCENT` |
| `cpu_weight range is [1, 500]` | out-of-range `CPU_WEIGHT` |
| `memory_limit range is [0, INT_MAX] or equals to -1` | out-of-range `MEMORY_LIMIT` |
| `The min_cost value can't be less than 0.` | negative `MIN_COST` |
| `admin_group must have at least one concurrency` | `ALTER RESOURCE GROUP admin_group SET CONCURRENCY 0` |
| `resource group is used by at least one role` | `DROP` while `pg_authid.rolresgroup` still points at it (`resgroupcmds.c:2013`) |
| `cannot drop default resource group "<n>"` | `DROP default_group` / `admin_group` / `system_group` |
| `cannot drop resource group "<n>"` + hint `The resource group is currently managing <n> query(ies)` | `DROP` while queries are still running in it (`resgroup.c:639`) |
| `must be superuser to create/alter/drop resource groups` | non-superuser DDL |
| `canceling statement due to resource group waiting timeout` | `gp_resource_group_queuing_timeout` fired |
| `cgroup is not properly configured to use the cpuset feature` | cgroup cpuset controller unusable |
| `resource group must be enabled to use cpuset feature` | manager is not `group`/`group-v2` |

## pg_resgroup_move_query

| | 7.x | 6.x |
|---|---|---|
| Schema | `pg_catalog` | `gp_toolkit` |
| Signature | `pg_resgroup_move_query(pid int4, groupname text) → bool` | `gp_toolkit.pg_resgroup_move_query(session_id int4, groupid text) → bool` |
| First argument | backend **PID** | **session id** (`pg_stat_activity.sess_id`) |
| Implementation | built-in, `src/backend/utils/resgroup/resgroup_helper.c:458` | C library `gp_resource_group` from `gpcontrib/gp_internal_tools/` |
| Privilege | superuser only (`must be superuser to move query`) | `EXECUTE` granted to `public` |
| Companion | — | `gp_toolkit.pg_resgroup_check_move_query(int, oid)` |

Refusals in 7.x (`resgroup_helper.c:458` onward, plus `resgroup.c`):

```
ERROR:  resource group is not enabled
ERROR:  must be superuser to move query
ERROR:  cannot move myself
ERROR:  cannot find process: <pid>
ERROR:  cannot move a process from bypassed group
ERROR:  process <pid> is in IDLE state          -- also what a *queued* target gives
ERROR:  cannot move a process to the system_group
ERROR:  cannot move query while a resource group is being edited
ERROR:  cannot get slot in resource group <id>  -- resgroup.c:3769
ERROR:  cannot send signal to process           -- resgroup.c:3668
ERROR:  target process failed to move to a new group  -- resgroup.c:3738
```

The `group <id> doesn't have enough memory on master/segment, expect:…, available:…` errors
are **6.x only** (`6.x resgroup.c:5125` and `:5153`); on 7.x they survive only as dead
`start_matchsubs` lines in `resgroup_move_query.sql` and are never raised.

## In-tree tests

| Target | Schedule | Notes |
|---|---|---|
| `make -C src/test/isolation2 installcheck-resgroup` | `isolation2_resgroup_v1_schedule` (6.x: `isolation2_resgroup_schedule`) | starts with `resgroup_auxiliary_tools_v1` which does the `gpconfig`/`gpstop` switch |
| `make -C src/test/isolation2 installcheck-resgroup-v2` | `isolation2_resgroup_v2_schedule` | 7.x only; `resgroup_auxiliary_tools_v2` sets `group-v2` |
| `make installcheck-resgroup` (top level) | — | both lines |
| `make installcheck-resgroup-v2` (top level) | — | 7.x only |

Both schedules use `--init-file=src/test/regress/init_file --init-file=./init_file_resgroup`
and the database `isolation2resgrouptest`.

References:
[Use resource groups](https://greengagedb.org/en/docs-gg/current/resource_groups.html) ·
[CREATE RESOURCE GROUP](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/create_resource_group.html) ·
[ALTER RESOURCE GROUP](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/alter_resource_group.html) ·
[DROP RESOURCE GROUP](https://greengagedb.org/en/docs-gg/current/reference/sql_commands/drop_resource_group.html) ·
[pg_resgroup](https://greengagedb.org/en/docs-gg/current/reference/pg_catalog/pg_resgroup.html) ·
[pg_resgroupcapability](https://greengagedb.org/en/docs-gg/current/reference/pg_catalog/pg_resgroupcapability.html)
(all `/current/` pages describe the 6.x attribute set; the 7.x deltas above come from the source tree)
