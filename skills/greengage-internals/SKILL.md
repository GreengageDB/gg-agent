---
name: greengage-internals
description: Make MPP-correct Greengage backend changes - QD/QE roles and Gp_role, gangs and dispatch, outfast.c/readfast.c plan serialization, Motion and slices, locus, GPORCA's silent fallback, FTS outside a transaction, append-optimized aux relkinds, utility mode, fault injection, gpexpand protection. Use when editing C under src/backend/cdb, src/backend/fts or src/backend/gpopt, or on `could not deserialize unrecognized node type`, `cannot create Motion on QE slice`, or an isolation2 test that hangs instead of failing.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "7.x (6.x deltas noted)"
---

# Greengage internals: what single-node instincts get wrong

Greengage 7.x is PostgreSQL **12.22** cut into an MPP engine: one coordinator backend
plans, N segment backends execute, and `Motion` plan nodes move tuples between them. 6.x is
PostgreSQL 9.4.26 with the same shape and different spellings.

A change that is correct on one node can be wrong here in ways the compiler and a default
`installcheck-good` run will not catch. This skill is the list of those ways.

Full component map — 21 areas, where each lives, what breaks:
[reference/greengage-vs-postgres.md](reference/greengage-vs-postgres.md).

## Before you edit: which of the three processes is this?

Every backend has a role, `Gp_role` (`src/include/cdb/cdbvars.h:64-67`). Ask which values
reach your code before you write a line.

| Role | Who | What is true there |
|---|---|---|
| `GP_ROLE_DISPATCH` | the coordinator backend (QD) | plans, dispatches, owns the distributed transaction, owns sequences |
| `GP_ROLE_EXECUTE` | a segment backend (QE) | executes one slice; **no** planner, no gang of its own |
| `GP_ROLE_UTILITY` | a direct connection to one node | dispatches nothing at all |
| `GP_ROLE_UNDEFINED` | not yet set | 7.x default of the `gp_role` GUC |

The GUC is `gp_role` on 7.x (`guc_gp.c:4590`, default `"undefined"`). 6.x has **both**
`gp_session_role` and `gp_role`, both defaulting to `dispatch`.
**Use `PGOPTIONS='-c gp_session_role=utility'` — that is the spelling that works on both
lines.** 7.x keeps `gp_session_role` as a rename alias onto `gp_role` (`guc.c:4761`), while
on 6.x setting only `gp_role` leaves `Gp_session_role` at `dispatch` and `postinit.c:1196`
rejects the connection with `connections to primary segments are not allowed`.

**Rules:**

- Never assume the process that plans is the process that executes. `Gp_role` is not a
  static property of the binary; it is per-backend.
- Anything you compute on the QD and need on a QE must be **serialized and dispatched**.
  Anything you compute on a QE and need on the QD must ride a Motion or a dispatch result.
- Never call a QD-only facility from a QE path. Sequences are the worked example: a QE
  does not own the sequence, it round-trips to the QD over the dispatch connection —
  `nextval_internal()` branches on `Gp_role == GP_ROLE_EXECUTE`
  (`src/backend/commands/sequence.c:750`) into `cdb_sequence_nextval_qe()` (`:2140`).

## The wire is `outfast.c`/`readfast.c`, not `outfuncs.c`/`readfuncs.c`

Dispatch serializes the plan in a **binary** format. Editing the text serializers does not
touch it.

`readfast.c:224-225` does `#define COMPILING_BINARY_FUNCS` then `#include "readfuncs.c"`,
and `outfast.c:329-330` does the same with `outfuncs.c`. Whatever differs in the binary
form is walled off in the text file behind `#ifndef COMPILING_BINARY_FUNCS` and
re-implemented in the binary file. On 7.x: `outfuncs.c` has 36 such blocks, `outfast.c`
defines 43 of its own `_out*` functions; `readfuncs.c` has 14 blocks, `readfast.c` defines
81 `_read*`.

Most blocks wall off a whole `_out*`/`_read*` function, but **some wall off a single
field** — `WRITE_NODE_FIELD(invalItems)` at `outfuncs.c:364` and `WRITE_NODE_FIELD(flow)`
at `:498` are written only in the text form. Never assume a node is "shared" because its
function is.

**Rule: after adding or reordering a field on any node that crosses the wire, open
`outfast.c` and `readfast.c` and check both.** If the node has no binary-specific
definition, the shared one covers you. If it does, you have two more files to edit.

The failure is a QE error:

```
ERROR:  could not deserialize unrecognized node type: 1936287860
```

Source: `src/backend/nodes/readfast.c:2601`. Read the number:

| `%d` value | Meaning | Fix |
|---|---|---|
| Huge / garbage / changes run to run | Stream slip: a `WRITE_*FIELD` with no matching `READ_*FIELD` earlier in the message | Diff the `WRITE_*` sequence of the writer against the `READ_*` sequence of the reader, field by field, in order |
| Small and plausible (a real `NodeTag`) | The reader's `switch` has no `case T_x:` | Add the reader case |

Do not "fix" this by widening a buffer or adding a cast. It is always a field-list
mismatch.

## ORCA is a second, independent implementation of your plan node

Greengage has two planners. `optimizer=on` (default when built with ORCA,
`guc_gp.c:1815-1823`) runs GPORCA; `optimizer=off` runs the Postgres planner with
Greengage extensions.

They do not share plan-node construction. `CTranslatorDXLToPlStmt.cpp` (6854 lines) builds
each node itself — `Motion *motion = MakeNode(Motion);` at line 2380, then assigns fields
one at a time.

**Rule: a plan-node field that only `createplan.c` sets is zero under ORCA.** That is not
an error — it is a wrong answer. Every new field on a dispatched plan node needs a matching
assignment in the translator, or an explicit decision that ORCA never produces that node.
ORCA's motion switch (`CTranslatorDXLToPlStmt.cpp:2560-2596`) emits only four of the six
7.x motion types, so `MOTIONTYPE_GATHER_SINGLE` and `MOTIONTYPE_OUTER_QUERY` are
planner-only.

### Your "ORCA test" may not be running ORCA

ORCA **falls back silently**. On an unsupported feature it returns no plan and the caller
runs the Postgres planner. The INFO message explaining why is gated behind
`optimizer_trace_fallback`, which **defaults to `false`** (`guc_gp.c:1840-1847`).

Confirm which planner ran, every time, from the plan itself:

```sql
SET optimizer_trace_fallback = on;   -- makes the fallback reason visible at INFO
EXPLAIN <query>;
-- last line is  Optimizer: GPORCA           or   Optimizer: Postgres-based planner
```

`src/backend/commands/explain.c:968-971`. **6.x prints different strings** —
`Optimizer: Pivotal Optimizer (GPORCA)` and `Optimizer: Postgres query optimizer`
(6.x `explain.c:658-661`) — so a grep written for one line silently matches nothing on the
other.

Costs from the two planners are not comparable. Never conclude "ORCA is slower" from a
cost number.

## A Motion may not sit directly on a Motion

`make_motion()` asserts it (`src/backend/optimizer/plan/createplan.c:7297`):

```c
Assert(lefttree);
Assert(!IsA(lefttree, Motion));
```

and refuses to run off the coordinator at all (`createplan.c:7286-7290`):

```
ERROR:  cannot create Motion on QE slice
```

**Rule: when a path that already plans to a Motion needs redistributing again, interpose a
pass-through node so the two motions land in adjacent slices.** Do not delete the assert.
It guards the slice cut: `Motion` is where `cdbllize_build_slice_table()`
(`src/backend/cdb/cdbllize.c:1144`) splits the plan, and two stacked Motions produce a
slice with no plan in it.

7.x motion types (`src/include/nodes/plannodes.h:1489-1494`): `GATHER`, `GATHER_SINGLE`,
`HASH`, `BROADCAST`, `EXPLICIT`, `OUTER_QUERY`. **6.x has only three**
(`plannodes.h:1277-1279`): `HASH`, `FIXED`, `EXPLICIT`, with a separate `isBroadcast`
flag — a 6.x backport cannot use `MOTIONTYPE_BROADCAST`.

Related: `motion_sanity_walker()` / `motion_sanity_check()` (`cdbllize.c:1468`, `:1633`)
exist because plan walkers that do not recognise a new node type mis-slice the plan. A new
plan node needs teaching to `src/backend/optimizer/util/walkers.c` and `cdbllize.c`.

## Distribution keys are matched by expression identity

A path's **locus** (`src/include/cdb/cdbpathlocus.h:41-62`: `Entry`, `SingleQE`, `General`,
`SegmentGeneral`, `OuterQuery`, `Replicated`, `Hashed`, `HashedOJ`, `Strewn`) drives which
motions the planner inserts. `cdbpathlocus_get_distkey_exprs()` (`cdbpathlocus.c:535`)
resolves the hash key by calling `cdbpullup_findEclassInTargetList()` (`cdbpullup.c:241`)
against the subplan targetlist.

**Rule: never copy, flatten or re-stamp an expression between planning stages without
checking that the distribution key still matches.** The match is structural, so an
equivalent-but-not-identical expression stops matching and planning dies with:

```
ERROR:  could not find hash distribution key expressions in target list
```

`createplan.c:8251`.

## FTS runs outside a transaction — no syscache, no catalog, no ACL

The Fault Tolerance Service on the coordinator probes segments; segments answer in
`src/backend/fts/ftsmessagehandler.c`. The connection is flagged `am_ftshandler` during
startup-packet processing (`src/backend/postmaster/postmaster.c:2598`), and
`src/backend/tcop/postgres.c:5493` routes it to `HandleFtsMessage()` **instead of**
`exec_simple_query()`. No transaction is started. On a mirror there is no heap access at
all — authentication is faked and the session user is set standalone, because
"Heap access is not possible on mirror, which is in standby mode"
(`src/backend/utils/init/postinit.c:900-909`).

**Rule: no code reachable from `HandleFtsMessage()` may do a syscache lookup, a catalog
scan, or a permission check.** The existing precedent is in core:

```c
/* src/backend/utils/misc/guc.c:8366, AlterSystemSetConfigFile() */
if (!am_ftshandler && !superuser())
    ereport(ERROR, ... "must be superuser to execute ALTER SYSTEM command" ...);
```

That bypass exists because promotion calls `UnsetSyncStandbysDefined()`
(`src/backend/replication/gp_replication.c:621`), which writes
`synchronous_standby_names` through `AlterSystemSetConfigFile()`. Add a *second*
permission check on that path and mirror promotion stops working — with no test failure
until an HA scenario runs.

Two more FTS invariants worth not breaking:

- Mirrors sit in `PM_RECOVERY`. The postmaster must return `CAC_MIRROR_READY`
  (`postmaster.c:3002-3003`, guarded by `GetMirrorReadyFlag()`) **before** any newer
  "not consistent yet" rejection, or FTS can never reach a mirror.
- Segment identity lives in `internal.auto.conf` (`src/include/catalog/catalog.h:28`).
  A wrong or missing `gp_dbid` shows up as
  `message type: %s received dbid:%d doesn't match this segments configured dbid:%d`
  (`ftsmessagehandler.c:441`) — `FATAL` on a cassert build, only `WARNING` otherwise.
  That is a `pg_basebackup --target-gp-dbid` / `pg_rewind` graft failure, not an FTS bug.

## Every relkind check misses the AO auxiliary relations

An append-optimized table owns three auxiliary **heap** relations — segfile map, block
directory, visibility map — reachable through `pg_appendonly.segrelid` / `blkdirrelid` /
`visimaprelid` (`src/include/catalog/pg_appendonly.h:30-32`). Their relkinds are
Greengage-only (`src/include/catalog/pg_class.h:173-175`; same three values on 6.x at
`:172-174`):

| Constant | Value | Relation |
|---|---|---|
| `RELKIND_AOSEGMENTS` | `'o'` | `pg_aoseg.*` segment-file map |
| `RELKIND_AOBLOCKDIR` | `'b'` | `pg_aoblkdir.*` block directory |
| `RELKIND_AOVISIMAP` | `'M'` | `pg_aovisimap.*` visibility map |

**Rule: never add a relkind assertion or a `switch` over relkinds without deciding what
`'o'`, `'b'` and `'M'` do.** They are heaps; they get vacuumed, truncated and
relfilenode-swapped like heaps. `RELKIND_HAS_STORAGE()` already lists all three
(`pg_class.h:199-207`) — keep the upstream macro unchanged and add a separate AO-aux
branch beside it rather than editing it.

**Second trap, 7.x only.** On 7.x, AO is a table access method (`ao_row` / `ao_column`,
`src/include/catalog/pg_am.dat:21,24`), and a `RELKIND_PARTITIONED_TABLE` **gets a `relam`
too** — from `USING`, from `default_table_access_method`, or copied off its parent
(`src/backend/commands/tablecmds.c:786-813`). So `RelationIsAoRows()`
(`src/include/utils/rel.h:442`) returns true for a `RELKIND_PARTITIONED_TABLE` that has no
storage whatsoever. Use the `Storage` variants when you are about to touch files:

```c
#define RelationStorageIsAoRows(relation) \
    ((relation)->rd_rel->relam == AO_ROW_TABLE_AM_OID && \
        (relation)->rd_rel->relkind != RELKIND_PARTITIONED_TABLE)   /* rel.h:445 */
```

**6.x has no table AM at all.** It keys on `pg_class.relstorage` — `'h'` heap, `'a'` AO
row, `'c'` AO column, `'x'` external (6.x `pg_class.h:205-210`). `relstorage` does not
exist on 7.x, and `RelationIsAoRows` does not exist on 6.x. Any AO patch needs writing
twice.

## Utility mode is for reading, never for DDL

`PGOPTIONS='-c gp_session_role=utility' psql -p <segment port> -d <db>` attaches to one
node with `Gp_role == GP_ROLE_UTILITY`. Use that spelling, not `gp_role=utility`, which
only works on 7.x — see the role table above.

Dispatch is gated on the role: `src/backend/tcop/utility.c` tests
`Gp_role == GP_ROLE_DISPATCH` at 15 sites before dispatching a utility statement, and
`src/backend/commands/tablecmds.c` at 49 sites. In utility mode **none of those fire**.

**Rule: run only `SELECT` and catalog inspection in utility mode.** A `CREATE`, `ALTER` or
`DROP` executed there lands on exactly one node and desynchronises the cluster catalog —
detected later by `gpMgmt/bin/gpcheckcat`, repaired by hand. There is no guard that stops
you.

isolation2 uses the same mechanism. There the session number before `U` is a **content-id**,
not a session id: `-1U:` is the coordinator, `0U:`/`1U:`/`2U:` are segments, `*U:` fans out
to the coordinator and all primaries, and `R` is retrieve mode
(`src/test/isolation2/sql_isolation_testcase.py:865-890`; the connection is opened with
`-c gp_role=utility` at `:372` and `:403`).

## A new predefined GUC must be classified, or the backend will not start

Every predefined GUC is either dispatched to QEs or not. The two lists live in
`src/backend/utils/misc/guc_gp.c:4978-4986` and are `#include`d from
`src/include/utils/sync_guc_name.h` and `src/include/utils/unsync_guc_name.h` — **those two
header files are where a new name goes**. Greengage's own GUC definitions live in
`guc_gp.c`, not `guc.c`.

Miss it and `gpdb_assign_sync_flag()` (`guc_gp.c:4999`) raises at startup:

```
ERROR:  Neither sync_guc_names_array nor unsync_guc_names_array contains predefined guc name: <name>
```

Consistency is covered by the isolation2 test `sync_guc`
(`src/test/isolation2/sql/sync_guc.sql`), which checks a GUC's value **and its
`reset_val`** agree across QD and QEs.

## The gpexpand `FATAL` is intentional — do not soften it

`gp_expand_protect_catalog_changes()` (`src/backend/utils/misc/gpexpand.c:108`) runs before
every catalog write, from `src/backend/access/heap/heapam.c:1984`, `:2609`, `:3097`. Two
outcomes:

| Condition | Level | Message |
|---|---|---|
| expansion in progress, lock unavailable | `ERROR` | `gpexpand in progress, catalog changes are disallowed.` |
| this session's gang predates the expansion | `FATAL` | `cluster is expanded from version %d to %d, catalog changes are disallowed` |

**Rule: never downgrade the second to `ERROR`.** `ERROR` would leave the session alive
holding a gang built from the *old*, smaller segment set — it would keep computing, on the
wrong number of segments, silently wrong. Killing the backend is the point. Clients that
predate the change may surface it only as
`server closed the connection unexpectedly`; that is expected.

## A removed fault point hangs the test — it does not fail it

Fault injection is `src/backend/utils/misc/faultinjector.c` plus the
`gpcontrib/gp_inject_fault` extension. Fifteen named fault types
(`sleep`, `suspend`, `resume`, `skip`, `error`, `fatal`, `panic`, `infinite_loop`,
`wait_until_triggered`, `finish_pending`, `interrupt`, `segv`, `status`,
`exit_no_callbacks`, `reset` — `src/include/utils/faultinjector_lists.h`). Measured on
7.x: **193** distinct `SIMPLE_FAULT_INJECTOR("…")` point names, and `gp_inject_fault` is
referenced by **102** isolation2 SQL files and 35 regress SQL files.

A test typically arms a fault, starts a session that will block on it, waits with
`gp_wait_until_triggered_fault(name, n, dbid)`, then releases it.

**Rule: if your change moves, renames or deletes a code path, grep it for
`SIMPLE_FAULT_INJECTOR` and `FaultInjector_InjectFaultIfSet` first.** When the point stops
being reached, `gp_wait_until_triggered_fault` never returns and the test **hangs forever**
instead of failing — the dominant post-refactor isolation2 symptom. Look for the missing
fault name before you look at your logic.

Build gating differs by line and is easy to get backwards:

| Line | `--enable-debug-extensions` default | Consequence |
|---|---|---|
| 7.x | **yes** (`configure.in:225`) | `FAULT_INJECTOR` is defined unless you pass `--disable-debug-extensions` |
| 6.x | **no** (`configure.in:212`) | you must pass `--enable-debug-extensions`, or `SIMPLE_FAULT_INJECTOR` compiles to nothing (`faultinjector.h:152-158`) |

## `-- start_ignore` and `GP_IGNORE:` are documentation, not regressions

Answer files are compared through `gpdiff.pl`/`atmsort.pm`, never with raw `diff`. Two
markers matter when you read a diff:

- `-- start_ignore` / `-- end_ignore` in a `.sql` file: atmsort ignores every result until
  the next `end_ignore`, prefixes the skipped output with `GP_IGNORE`, and `diff -I` then
  drops those lines (`src/test/regress/atmsort.pl:226-235`). 162 files under
  `src/test/regress/sql` mention `start_ignore`.
- `GP_IGNORE:` lines in a `.out` file are that prefix, already applied.

**Rule: treat an ignored block as a recorded, accepted limitation, not as dead weight.**
Greengage uses it to document behaviour that is known-different — an unsupported plan
shape, a platform-dependent message. Removing the marker to "see the real output" turns a
documented limitation into a red test. Regeneration method:
[greengage-answer-files](../greengage-answer-files/SKILL.md).

## What not to do

| Do not | Because |
|---|---|
| Assume the text out/read funcs are the wire | The wire is `outfast.c`/`readfast.c`; the text pair may not be compiled into it |
| Add a plan-node field without touching `src/backend/gpopt/translate/` | ORCA leaves it zero and returns wrong results with no error |
| Trust that a test with `optimizer=on` exercised ORCA | ORCA falls back silently; `optimizer_trace_fallback` is off by default |
| Delete the `!IsA(lefttree, Motion)` assert to make a plan build | It guards the slice cut; you will get a slice with no plan |
| Add a catalog or permission check on an FTS-reachable path | FTS has no transaction; mirror promotion breaks and no regress test notices |
| Edit `RELKIND_HAS_STORAGE()` to fit a new case | Add a separate AO-aux branch beside it instead |
| Run DDL in utility mode "just to test something" | Nothing is dispatched; the cluster catalog desynchronises silently |
| Turn the gpexpand `FATAL` into an `ERROR` | A stale gang would keep computing against the old segment count |
| Chase a hanging isolation2 test as a deadlock | First check whether the fault point it waits on still exists |
| Port a 7.x AO or Motion patch to 6.x unchanged | 6.x has `relstorage` not `relam`, and three motion types not six |
| Cite `main` or the working tree as the source of truth | Verify against `refs/remotes/origin/7.x` / `refs/remotes/origin/6.x` |

## Verifying a claim about this tree

```bash
cd <greengage-checkout>
S7=refs/remotes/origin/7.x
git show $S7:src/include/cdb/cdbvars.h | grep -n GP_ROLE_
git grep -n "SIMPLE_FAULT_INJECTOR" $S7 -- src/backend/cdb/
```

Never write bare `origin/7.x`: a local branch of that literal name can shadow the remote
ref, and git resolves it silently with only a `warning:`. Always use the
`refs/remotes/origin/` form, and never cite a feature branch or the working tree.

See also: [greengage-debug](../greengage-debug/SKILL.md),
[greengage-testing](../greengage-testing/SKILL.md),
[greengage-answer-files](../greengage-answer-files/SKILL.md),
[greengage-build](../greengage-build/SKILL.md),
[greengage-query-performance](../greengage-query-performance/SKILL.md),
[greengage-cluster-ops](../greengage-cluster-ops/SKILL.md)
