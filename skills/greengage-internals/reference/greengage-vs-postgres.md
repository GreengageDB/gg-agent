# Greengage vs vanilla PostgreSQL — the differences map

Twenty-one places where Greengage is not the PostgreSQL you know. For each: what it is,
where it lives, and **why it bites** — the failure you get when you change it with
single-node instincts.

Every path below was checked against `refs/remotes/origin/7.x`. Line numbers are 7.x.
6.x deltas are called out inline. 7.x is PostgreSQL **12.22**; 6.x is **9.4.26**.

---

## 1. Process roles: coordinator (QD) vs segment (QE)

One coordinator backend ("query dispatcher", QD) plans a query and dispatches it to N
segment backends ("query executors", QE), each a full postgres instance owning a slice of
the data. The role is `Gp_role`, values `GP_ROLE_UNDEFINED`, `GP_ROLE_UTILITY`,
`GP_ROLE_DISPATCH`, `GP_ROLE_EXECUTE` (`src/include/cdb/cdbvars.h:64-67`).
`gp_session_id` ties a QD session to its QEs;
`IS_QUERY_EXECUTOR_BACKEND()` is `Gp_role == GP_ROLE_EXECUTE && gp_session_id > 0`
(`cdbvars.h:756`).

The GUC is `gp_role` on 7.x (default `"undefined"`, `guc_gp.c:4590`). 6.x has **both**
`gp_session_role` and `gp_role` (`guc_gp.c:5068`, `5079`), both defaulting to `dispatch`.

**Why it bites:** upstream code assumes one process does everything. New logic on a shared
path silently runs N+1 times, or runs on the QD only and never reaches the data. Sequence
allocation is the canonical example: a QE does not own the sequence, it asks the QD over
the dispatch connection — `nextval_internal()` branches on `Gp_role == GP_ROLE_EXECUTE`
(`src/backend/commands/sequence.c:750`) into `cdb_sequence_nextval_qe()` (`:2140`).

## 2. Gangs and dispatch

The QD allocates a **gang** of QE backends per slice and sends the serialized plan, params
and GUCs over libpq. Code: `src/backend/cdb/dispatcher/` — `cdbdisp.c`, `cdbdisp_async.c`,
`cdbdisp_query.c`, `cdbdisp_dtx.c`, `cdbgang.c`, `cdbgang_async.c`, `cdbconn.c`, `cdbpq.c`.
`src/backend/cdb/dispatcher/README.md` is the authoritative API document.

Four gang types (README; enum `src/include/nodes/plannodes.h:223-227`, whose fifth value
`GANGTYPE_UNALLOCATED` is the root slice the QD runs itself):
`GANGTYPE_ENTRYDB_READER` (one process on the coordinator), `GANGTYPE_SINGLETON_READER`
(one process on one segment), `GANGTYPE_PRIMARY_READER` (a 1-gang or N-gang on the
segments), `GANGTYPE_PRIMARY_WRITER` (N processes, owns DTM; **at most one per session,
and reader gangs cannot exist without it**).

`PQsendGpQuery_shared()` (`cdbpq.c:7`) is a libpq graft: it swaps `conn->outBuffer` for a
pre-serialized shared query buffer so one plan text is sent to every QE without N copies.

**Why it bites:** gang-creation failures look like query bugs but are not.
`failed to acquire resources on one or more segments` with detail
`Segments are in reset/recovery mode.` comes from `cdbgang_async.c:370`, not from your
planner change. Any change to libpq's send path can break `PQsendGpQuery_shared` for the
whole cluster.

## 3. Plan serialization: `outfast.c` / `readfast.c`, not the text funcs

Dispatch uses a **binary** node serializer: `src/backend/nodes/outfast.c` (writer) and
`readfast.c` (reader). They are not independent files — `readfast.c:224-225` does
`#define COMPILING_BINARY_FUNCS` then `#include "readfuncs.c"`, and `outfast.c:329-330`
does the same with `outfuncs.c` (the dependency is spelled out in
`src/backend/nodes/Makefile:20-22`). Whatever differs from the text form is walled off in
the text file behind `#ifndef COMPILING_BINARY_FUNCS` and re-implemented in the binary
file. Most blocks wall off a whole function; a few wall off a **single field**
(`WRITE_NODE_FIELD(invalItems)` at `outfuncs.c:364`, `WRITE_NODE_FIELD(flow)` at `:498`).

Measured on 7.x: `outfuncs.c` has 36 `#ifndef COMPILING_BINARY_FUNCS` blocks and
`outfast.c` defines 43 `_out*` functions of its own; `readfuncs.c` has 14 such blocks and
`readfast.c` defines 81 `_read*` functions of its own.

**Why it bites:** for any node in that walled-off set, adding a field to `outfuncs.c` and
`readfuncs.c` does **not** touch the wire. The writer and reader drift and the QE reports
`could not deserialize unrecognized node type: %d` (`readfast.c:2601`). A garbage,
enormous `%d` means the byte stream slipped — a `WRITE_*FIELD` with no matching
`READ_*FIELD`. A small, real tag means the reader's `switch` has no `case` for it.

## 4. Motion nodes and slices

`Motion` is the data-movement plan node. 7.x motion types (`plannodes.h:1489-1494`):
`MOTIONTYPE_GATHER`, `MOTIONTYPE_GATHER_SINGLE`, `MOTIONTYPE_HASH`,
`MOTIONTYPE_BROADCAST`, `MOTIONTYPE_EXPLICIT`, `MOTIONTYPE_OUTER_QUERY`.
**6.x has only three** (`plannodes.h:1277-1279`): `MOTIONTYPE_HASH`, `MOTIONTYPE_FIXED`,
`MOTIONTYPE_EXPLICIT`, with a separate `isBroadcast` flag on the node.

A plan is cut at Motions into **slices**, each run by its own gang. `ExecSlice` and
`SliceTable` live in `src/include/executor/execdesc.h:81` and `:150`; 6.x calls the struct
plain `Slice` (`execdesc.h:47`). The slice table is built by
`cdbllize_build_slice_table()` (`src/backend/cdb/cdbllize.c:1144`); the Motions a SubPlan
needs are added by `cdbllize_decorate_subplans_with_motions()` (`cdbllize.c:720`), and
`src/backend/cdb/cdbmutate.c` ("Parallelize a PostgreSQL sequential plan tree") does the
rest of the parallelization.
Execution: `src/backend/executor/nodeMotion.c`.

**Why it bites:** `make_motion()` asserts `!IsA(lefttree, Motion)`
(`src/backend/optimizer/plan/createplan.c:7297`) — a Motion may never sit directly on a
Motion; interpose a pass-through node so the two occupy adjacent slices. It also refuses
to build at all off the coordinator: `cannot create Motion on QE slice`
(`createplan.c:7290`). `cdbllize.c:1468` `motion_sanity_walker()` exists precisely because
plan walkers that do not know a new node type mis-slice the plan.

## 5. Interconnect

Tuple transport between slices: `src/backend/cdb/motion/`. Three implementations selected
by `gp_interconnect_type` (`guc_gp.c:496-502`, `:4859`): `udpifc` (**default**,
`ic_udpifc.c`), `tcp` (`ic_tcp.c`), and `proxy` (`ic_proxy_*.c`, compiled only under
`ENABLE_IC_PROXY`, i.e. `--enable-ic-proxy`). Tuple (de)serialization is `tupser.c`;
shared driver code is `ic_common.c`.

**Why it bites:** the non-default transports are barely exercised, and the proxy is not
even compiled unless you configured `--enable-ic-proxy` (default `no`,
`configure.in:819`). Worse, `installcheck-ic-tcp` and `installcheck-ic-proxy` in
`src/test/isolation2` are wrapped in `ifeq ($(findstring gp_interconnect_type=…,
$(PGOPTIONS)) …)` (`src/test/isolation2/Makefile:106-114`): run either target without the
matching `PGOPTIONS` and it runs **nothing** and reports success.

## 6. Locus and distribution policy

Every table carries a distribution policy in `gp_distribution_policy`
(`src/include/catalog/gp_distribution_policy.h`): `policytype`, `numsegments`, and an
`int2vector distkey`. Hidden system column `gp_segment_id` is attribute number **-7**
(`src/include/access/sysattr.h:27`).

The planner tracks placement per path as a **locus**
(`src/include/cdb/cdbpathlocus.h:41-62`): `Entry`, `SingleQE`, `General`,
`SegmentGeneral`, `OuterQuery`, `Replicated`, `Hashed`, `HashedOJ`, `Strewn`.
Logic: `src/backend/cdb/cdbpathlocus.c`, `cdbpullup.c`, `cdbpath.c`.
`cdbpathlocus_get_distkey_exprs()` (`cdbpathlocus.c:535`) calls
`cdbpullup_findEclassInTargetList()` (`cdbpullup.c:241`) to match each distribution-key
equivalence member against a subplan targetlist.

**Why it bites:** the match is by expression identity. Any planner change that copies,
flattens or re-stamps expressions between stages can make an equivalent expression stop
comparing equal, and the plan dies with
`could not find hash distribution key expressions in target list`
(`createplan.c:8251`).

## 7. The two optimizers

**GPORCA** (`optimizer=on`, default when built with ORCA — `guc_gp.c:1815-1823`) is a C++
optimizer in `src/backend/gporca/`, glued to the backend by the **translator** in
`src/backend/gpopt/` (`translate/CTranslatorQueryToDXL.cpp` for Query→DXL,
`translate/CTranslatorDXLToPlStmt.cpp`, 6854 lines, for DXL→PlannedStmt).
The **Postgres planner** (`optimizer=off`) carries Greengage extensions:
`cdbgroupingpaths.c` (multi-stage and multi-DQA aggregation, 7.x; 6.x uses `cdbgroup.c`),
`cdbllize.c`, `cdbmutate.c`, `cdbpath.c`.

`EXPLAIN` names the one that ran: `Optimizer: GPORCA` or
`Optimizer: Postgres-based planner` (`src/backend/commands/explain.c:968-971`).
6.x prints different strings — `Optimizer: Pivotal Optimizer (GPORCA)` and
`Optimizer: Postgres query optimizer` (6.x `explain.c:658-661`).

**Why it bites, twice.**
(a) ORCA builds plan nodes itself — `Motion *motion = MakeNode(Motion)` at
`CTranslatorDXLToPlStmt.cpp:2380`, then assigns fields one by one. A field you add and set
only in `createplan.c` stays at its zero value under ORCA: **wrong results, no error**.
ORCA's motion switch emits only four of the six motion types
(`CTranslatorDXLToPlStmt.cpp:2560-2596`).
(b) ORCA **falls back silently**. On an unsupported feature it returns no plan and the
caller runs the Postgres planner; the explanatory INFO message is gated behind
`optimizer_trace_fallback`, which **defaults to false** (`guc_gp.c:1840-1847`). A test you
believe covers ORCA may cover neither.

## 8. Distributed transactions (DTX)

The QD drives two-phase commit across segments. `src/backend/cdb/cdbtm.c` holds the state
machine — 16 states from `DTX_STATE_NONE` through `DTX_STATE_PREPARED`,
`DTX_STATE_NOTIFYING_COMMIT_PREPARED`, `DTX_STATE_RETRY_ABORT_PREPARED`
(`src/include/cdb/cdbtm.h:32-83`). A distributed transaction is identified by a
`DistributedTransactionId gxid`, rendered into a gid by `dtxFormGid()` (`cdbtm.h:294`).
In-doubt resolution is `cdbdtxrecovery.c`; distributed snapshots layered over local ones
are `cdbdistributedsnapshot.c`; the dispatch side is `dispatcher/cdbdisp_dtx.c`.

Greengage extends the checkpoint WAL record with a `TMGXACT_CHECKPOINT` payload, replayed
by `redoDtxCheckPoint()` (`cdbtm.h:310`, called from
`src/backend/access/transam/xlog.c:6335`).

**Why it bites:** an xlog or xact refactor that drops the extended-checkpoint read or its
replay leaves segments unable to resolve prepared transactions after crash recovery. The
damage surfaces long after the change, as commits aborting on segments.

## 9. FTS and mirrors

A primary segment may have a WAL-streamed mirror (mirrorless clusters exist — see
`installcheck-mirrorless`). The Fault Tolerance Service runs on the
coordinator (`src/backend/fts/fts.c`, `ftsprobe.c`), probes segments, promotes mirrors and
rewrites `gp_segment_configuration`. `src/backend/fts/README` documents the protocol.

Segments answer probes in `src/backend/fts/ftsmessagehandler.c`. The connection is marked
`am_ftshandler` during startup-packet processing
(`src/backend/postmaster/postmaster.c:2598`) and `postgres.c:5493` routes it to
`HandleFtsMessage()` **instead of** `exec_simple_query()` — so there is no transaction,
and on a mirror there is no heap access at all (`postinit.c:900-909`:
"Heap access is not possible on mirror, which is in standby mode"; authentication is
faked). Three messages: probe, syncrep-off, promote (`ftsmessagehandler.c:450-460`).

Mirrors sit in `PM_RECOVERY`; the postmaster must answer `CAC_MIRROR_READY`
(`postmaster.c:3002-3003`, guarded by `GetMirrorReadyFlag()`) **before** any newer
"not consistent yet" rejection, or FTS can never reach a mirror.

**Why it bites:** any permission or catalog check newly added to a function FTS reaches
breaks mirror promotion. The existing graft is visible at
`src/backend/utils/misc/guc.c:8366` — `if (!am_ftshandler && !superuser())` in
`AlterSystemSetConfigFile()`, needed because `UnsetSyncStandbysDefined()`
(`src/backend/replication/gp_replication.c:621`) writes `synchronous_standby_names` from
the FTS handler. Add a second such check and promotion stops working.

## 10. Segment identity and the pg_basebackup / pg_rewind grafts

Each data directory carries its own identity in `internal.auto.conf`
(`GP_INTERNAL_AUTO_CONF_FILE_NAME`, `src/include/catalog/catalog.h:28`) holding `gp_dbid`
(a `PGC_POSTMASTER` GUC bound to `GpIdentity.dbid`, `guc_gp.c:3357`).

Both tools are grafted:

| Tool | Greengage addition | Where |
|---|---|---|
| `pg_basebackup` | `--target-gp-dbid` (writes `internal.auto.conf`, lays tablespaces out per dbid) | `pg_basebackup.c:368`, `:1472`, `:2748` |
| `pg_basebackup` | `-E` / `--exclude`, `--exclude-from=FILE` | `pg_basebackup.c:393-395` |
| `pg_basebackup` | `--force-overwrite` | `pg_basebackup.c:2300` |
| `pg_rewind` | `-S` / `--slot=SLOTNAME` | `pg_rewind.c:88`, `:109` |
| `pg_rewind` | never copy `internal.auto.conf` from the source | `filemap.c:129`, `:288` |

**Why it bites:** these are exactly the files upstream rewrites wholesale. A dropped graft
does not fail at recovery time — it fails later, when FTS probes the recovered segment and
gets `message type: %s received dbid:%d doesn't match this segments configured dbid:%d`
(`ftsmessagehandler.c:441`), which is `FATAL` on a cassert build and only `WARNING`
otherwise (`ftsmessagehandler.c:433-437`).

## 11. Append-optimized (AO) tables

Two extra storage flavours: AO row (`src/backend/access/appendonly/`) and AO column
(`src/backend/access/aocs/`). On 7.x they are real table access methods, `ao_row` and
`ao_column` (`src/include/catalog/pg_am.dat:21,24`), tested by `RelationIsAoRows()` /
`RelationIsAoCols()` / `RelationIsAppendOptimized()` (`src/include/utils/rel.h:442-475`).
**6.x has no table AM**: it uses `pg_class.relstorage`, `'h'` heap / `'a'` AO row /
`'c'` AO column / `'x'` external / `'v'` virtual / `'f'` foreign
(6.x `pg_class.h:205-210`). `relstorage` does not exist on 7.x.

Every AO table owns auxiliary **heap** relations — segfile map, block directory,
visibility map — pointed to by `pg_appendonly.segrelid` / `blkdirrelid` / `visimaprelid`
(`src/include/catalog/pg_appendonly.h:29-33`) and created by
`src/backend/catalog/{aoseg,aoblkdir,aovisimap,aocatalog}.c`. Their relkinds are
Greengage-only: `RELKIND_AOSEGMENTS 'o'`, `RELKIND_AOBLOCKDIR 'b'`,
`RELKIND_AOVISIMAP 'M'` (`src/include/catalog/pg_class.h:173-175`; the same three values
on 6.x at `:172-174`).
`RELKIND_HAS_STORAGE()` already lists all three (`pg_class.h:199-207`).

**Why it bites, twice.** (a) Any new relkind test, assertion or switch you add misses
`'o'`, `'b'`, `'M'`, and the aux relations then get skipped by vacuum, truncate or
relfilenode maintenance. Keep the upstream macro unchanged and add a separate AO-aux
branch beside it. (b) On 7.x a partitioned parent inherits `relam`, so
`RelationIsAoRows()` returns **true** for a `RELKIND_PARTITIONED_TABLE` that has no
storage at all (a partitioned parent's `relam` comes from `USING`, from
`default_table_access_method`, or from its own parent —
`src/backend/commands/tablecmds.c:786-813`) — that is why
`RelationStorageIsAoRows()` and `RelationStorageIsAO()` exist
(`rel.h:445`, `:477`). Pick the `Storage` variant whenever you are about to touch files.

## 12. Resource queues and resource groups

Two admission-control systems, selected by `gp_resource_manager`.
Resource queues (the default) are `src/backend/utils/resscheduler/resqueue.c` with catalogs
`pg_resqueue`, `pg_resqueuecapability`. Resource groups are
`src/backend/utils/resgroup/` plus `src/backend/utils/resource_manager/`, catalogs
`pg_resgroup`, `pg_resgroupcapability`. 7.x carries two cgroup backends —
`cgroup-ops-linux-v1.c` and `cgroup-ops-linux-v2.c`, with `cgroup.c` and
`cgroup_io_limit.c` (plus an IO-limit grammar, `io_limit_gram.y`); 6.x has a single
`resgroup-ops-linux.c`. Operationally, resource groups need cgroup v1 — see
[greengage-workload-management](../../greengage-workload-management/SKILL.md).

**Why it bites:** resource-group shared memory is wired into core startup, and the
queue side hooks lock waiting. Lock, wait-queue and pgstat changes touch both, and neither
is exercised by a default `installcheck-good` run — they have their own targets
(`installcheck-resgroup`, `installcheck-resgroup-v2` on 7.x, `installcheck-resource-queue`
on 7.x).

## 13. External tables and gpfdist

The read/write machinery is `src/backend/access/external/` — `external.c`, `url.c`,
`url_curl.c`, `url_custom.c`, `url_execute.c`, `url_file.c`. `gpfdist`, the parallel file
server, is a standalone binary in `src/bin/gpfdist/`.

7.x surfaces external tables as **foreign tables**: `gpcontrib/gp_exttable_fdw/` defines
the `gp_exttable_fdw` wrapper and `gp_exttable_server`, and re-provides `pg_exttable` as a
compatibility *function* plus a view over it
(`gpcontrib/gp_exttable_fdw/gp_exttable_fdw--1.0.sql:23,39`). 6.x has a real
`pg_exttable` **catalog**
(`src/backend/catalog/pg_exttable.c`) and `relstorage = 'x'`.

**Why it bites:** on 7.x an external table is a foreign table, so upstream FDW-path changes
apply to it, and code that still expects a Greengage-specific relstorage or a `pg_exttable`
catalog row is 6.x-shaped and will not compile or will silently not match.

## 14. Greengage catalogs

Extra system catalogs in `src/include/catalog/`: `gp_segment_configuration` (the cluster
topology table — `dbid`, `content`, `role`, `preferred_role`, `mode`, `status`, `port`,
`hostname`, `address`, `datadir`; `BKI_SHARED_RELATION`, OID 5036),
`gp_distribution_policy`, `gp_id`, `gp_fastsequence`, `gp_configuration_history`,
`gp_partition_template`, `gp_version_at_initdb`, `pg_appendonly`,
`pg_attribute_encoding`, `pg_type_encoding`, `pg_compression`, `pg_resqueue*`,
`pg_resgroup*`. They go through genbki exactly like upstream catalogs.

`gp_toolkit` is an **extension** on 7.x (`gpcontrib/gp_toolkit`, 58 views); on 6.x it is
`src/backend/catalog/gp_toolkit.sql` loaded by initdb.

Idiom: `select gp_segment_id, … from gp_dist_random('pg_class')` reads a catalog from
every segment. It is a parser special case, not a function
(`src/backend/parser/parse_clause.c:637`).

**Why it bites:** OID collisions with new upstream objects, and genbki tightening.
`gpMgmt/bin/gpcheckcat` is the cross-segment catalog consistency checker and is wired into
`make installcheck-world` via `installcheck-gpcheckcat`.

## 15. Fault injection

Backend fault points: `src/backend/utils/misc/faultinjector.c`, macros in
`src/include/utils/faultinjector.h`, type list in
`src/include/utils/faultinjector_lists.h`. Fifteen named types —
`sleep`, `fatal`, `panic`, `error`, `infinite_loop`, `suspend`, `resume`, `skip`, `reset`,
`status`, `segv`, `interrupt`, `finish_pending`, `wait_until_triggered`,
`exit_no_callbacks`. SQL interface: `gpcontrib/gp_inject_fault` —
`gp_inject_fault(name, type, db_id)` and longer overloads, plus
`gp_inject_fault_infinite()` and `gp_wait_until_triggered_fault(name, numtimes, db_id)`.

Measured on 7.x: **193** distinct `SIMPLE_FAULT_INJECTOR("…")` point names in the tree;
**102** isolation2 SQL files and 35 regress SQL files reference `gp_inject_fault`.

Build gating differs by line. 7.x: `--enable-debug-extensions` defaults to **yes**, so
`FAULT_INJECTOR` is defined unless you pass `--disable-debug-extensions`
(7.x `configure.in:225`, generated `configure`). 6.x: it defaults to **no**
(6.x `configure.in:212`) — you must pass `--enable-debug-extensions`. Without it,
`SIMPLE_FAULT_INJECTOR` compiles to nothing (`faultinjector.h:152-158`).

**Why it bites:** a refactor that moves or deletes the code path holding a fault point does
not fail the test — the fault never fires, the waiting session never wakes, and the test
**hangs forever**. That is the dominant post-refactor isolation2 failure mode.

## 16. Utility mode

`PGOPTIONS='-c gp_session_role=utility' psql -p <segment port>` connects directly to one
segment (or the coordinator) with `Gp_role == GP_ROLE_UTILITY`. **That spelling is the one
that works on both lines** — 7.x keeps `gp_session_role` as a rename alias onto `gp_role`
(`guc.c:4761`), whereas on 6.x `assign_gp_role` (`cdbvars.c:519`) sets only `Gp_role`, so
`Gp_session_role` stays `dispatch` and `postinit.c:1196` rejects the connection with
`connections to primary segments are not allowed`. `gp_role=utility` is 7.x-only for
client connections. Used by `gpMgmt` tooling and by isolation2,
whose `<content-id>U:` session prefixes open utility connections — `-1U:` the coordinator,
`0U:`/`1U:`/`2U:` segments, `*U:` the coordinator and all primaries, `R` retrieve mode
(`src/test/isolation2/sql_isolation_testcase.py:865-890`; the connection carries
`-c gp_role=utility`, `:372` and `:403`, or `-c gp_retrieve_conn=true`, `:391`).

**Why it bites:** dispatch is gated on the role. `src/backend/tcop/utility.c` tests
`Gp_role == GP_ROLE_DISPATCH` at 15 sites before dispatching a utility statement
(`tablecmds.c` has 49 such tests). In utility mode **nothing is dispatched**, so DDL
applies to the one node you are attached to and desynchronises the cluster catalog. Use
utility mode for read-only inspection only.

## 17. GUC dispatch lists

The QD keeps QE session GUCs consistent. Every predefined GUC must be classified into
`sync_guc_names_array` (dispatched to QEs) or `unsync_guc_names_array`
(`src/backend/utils/misc/guc_gp.c:4978-4986`). Both arrays are `#include`d from
`src/include/utils/sync_guc_name.h` and `src/include/utils/unsync_guc_name.h` — those two
header files are where a new name goes. Greengage's own GUC definitions live in `guc_gp.c`,
not `guc.c`. Classification is applied by `gpdb_assign_sync_flag()` (`guc_gp.c:4999`).

**Why it bites:** a predefined GUC in neither list aborts at startup with
`Neither sync_guc_names_array nor unsync_guc_names_array contains predefined guc name: %s`
(`guc_gp.c:5042-5046`). Coverage and QD/QE consistency are enforced by the isolation2 test
`sync_guc` (`src/test/isolation2/sql/sync_guc.sql`).

## 18. gpexpand catalog protection

`gp_expand_protect_catalog_changes()` (`src/backend/utils/misc/gpexpand.c:108`) runs before
every catalog write, called from `src/backend/access/heap/heapam.c:1984`, `:2609`, `:3097`.
It is a no-op off the coordinator and for a short allowlist of QD-only catalogs
(`gp_segment_configuration`, `gp_configuration_history`, `pg_description`,
`pg_shdescription`, `pg_statistic`, `pg_stat_last_operation`, `pg_stat_last_shoperation`,
`gp_auth_time_constraint`). Otherwise it raises one of two errors:

| Condition | Level | Message |
|---|---|---|
| expand lock unavailable | `ERROR` | `gpexpand in progress, catalog changes are disallowed.` |
| session's gang predates the expansion | `FATAL` | `cluster is expanded from version %d to %d, catalog changes are disallowed` |

**Why it bites:** the `FATAL` looks like a bug and is not. Downgrading it to `ERROR` would
let a session keep its stale gang and go on computing against the *old*, smaller segment
set. Do not "fix" it. Old clients may report only
`server closed the connection unexpectedly`.

## 19. gpMgmt

Python cluster-management tooling in `gpMgmt/bin/`: `gpinitsystem`, `gpstart`, `gpstop`,
`gpstate`, `gpconfig`, `gprecoverseg`, `gpinitstandby`, `gpactivatestandby`, `gpexpand`,
`gpcheckcat`, `gpaddmirrors`, `gpmovemirrors`, `gpdeletesystem`, `gpsync` (the Greengage
rename of `gpscp`, which is still the 6.x name), `analyzedb`, `minirepro`, `gpcheckperf`,
`gplogfilter`. Shared library code is `gppylib`.

**Why it bites:** these tools shell out to `pg_ctl`, `pg_basebackup` and `pg_rewind` and
**parse their output**. An option rename or a message reword upstream breaks the parser,
not the C code — and nothing in `src/test/regress` will notice. Coverage is the behave
suite (`gpMgmt/test/behave/mgmt_utils/*.feature`, run via `gpMgmt/Makefile.behave`).

## 20. Extra test harnesses

| Harness | Where | What it adds |
|---|---|---|
| regress + `greengage_schedule` | `src/test/regress/` | Greengage-only tests; new tests go here, never in the upstream-inherited schedules |
| isolation2 | `src/test/isolation2/` | multi-session specs with `1:` / `2:` prefixes, `U` utility and `R` retrieve connections; syntax is documented in `sql_isolation_testcase.py` |
| gpdiff layer | `src/test/regress/gpdiff.pl`, `atmsort.pl`, `atmsort.pm`, `init_file*` | sorts unordered result sets, applies matchsubs masks, honours `-- start_ignore` / `GP_IGNORE:` |
| behave | `gpMgmt/test/behave/` | Gherkin tests for the management utilities |
| GPORCA unit tests | `src/backend/gporca/` | CMake/Ninja + ctest, `gporca_test -U <Name>` |

**Why it bites:** answer files are compared **through gpdiff**, never with raw `diff`. A
"failure" may be a masking directive you removed. See
[greengage-answer-files](../../greengage-answer-files/SKILL.md).

## 21. The demo cluster

Development runs against gpdemo: `gpAux/gpdemo/` (`demo_cluster.sh`, `gpdemo-env.sh`,
`Makefile`). Defaults: `PORT_BASE ?= 7000`, `NUM_PRIMARY_MIRROR_PAIRS ?= 3`,
`WITH_MIRRORS = true`, `WITH_STANDBY = true`. Data directories land under
`gpAux/gpdemo/datadirs/` — coordinator `qddir/demoDataDir-1`, primaries
`dbfast{1,2,3}/demoDataDir{0,1,2}`, mirrors `dbfast_mirror{1,2,3}/…`, standby `standby/`.

Bring it up with `make create-demo-cluster`, **never** by running `demo_cluster.sh`
directly — the Makefile exports the environment the script needs. Then
`source gpAux/gpdemo/gpdemo-env.sh`, which sets `PGPORT` and
`COORDINATOR_DATA_DIRECTORY` (7.x also exports `MASTER_DATA_DIRECTORY` as an alias; 6.x has
only the master one).

**Why it bites:** sourcing `greengage_path.sh` alone is not enough. Without
`gpdemo-env.sh` every `gp*` utility aborts with `COORDINATOR_DATA_DIRECTORY not set!`.
Operations and recovery: [greengage-cluster-ops](../../greengage-cluster-ops/SKILL.md).
