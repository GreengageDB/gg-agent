---
name: greengage-debug
description: Diagnose Greengage crashes, assertion failures, hangs and wrong results - CSV segment logs, the Greengage-specific assert signature, minimal reproduction, gp_debug_linger, gp_inject_fault suspend/wait/reset, temporary elog instrumentation, gdb on a live QE, global-deadlock hangs, blast-radius triage. Use when a query kills a backend, when logs show `Unexpected internal error`, `FailedAssertion`, `was terminated by signal 11`, `Cluster validation failed`, or when a statement never returns.
license: Apache-2.0
metadata:
  author: GreengageDB
  version: "0.1.0"
  greengageVersion: "7.x (6.x deltas noted)"
---

# Debugging Greengage

## Greengage does not print `TRAP: FailedAssertion`

Upstream PostgreSQL writes `TRAP: FailedAssertion(...)` to stderr. Greengage replaces
`ExceptionalCondition()` (`src/backend/utils/error/assert.c:30-48`) with an `ereport(FATAL)`,
so an assert failure lands in the CSV log as **two separate fields**:

| CSV field | Content |
|---|---|
| `logseverity` | `FATAL` |
| `logmessage` | `Unexpected internal error` |
| `logdetail` | `FailedAssertion("<stringified condition>", File: "<file>.c", Line: <n>)` |
| `logstack` | a 30-frame symbolized backtrace, appended automatically |

Real in-tree example (`src/test/regress/expected/portals.out:1242`):

```
DETAIL:  FailedAssertion("!(!((heap)->bh_size == 0) && heap->bh_has_heap_property)", File: "binaryheap.c", Line: 161)
```

**Never grep for `TRAP:`** — the only `TRAP:` string left in the tree is
`TRAP: ExceptionalCondition: bad arguments`, which fires only when the assert machinery
itself is passed NULLs. Grep for `FailedAssertion` (or `BadArgument`, `BadState`,
`AssertImply failed`, `AssertEquivalent failed`, `UnalignedPointer` — the other
`errorType` strings in `src/include/c.h:831-854`).

Segfaults are also rewritten. The syslogger emits, at severity `PANIC`
(`src/backend/postmaster/syslogger.c:1356-1358`):

```
Unexpected internal error: Segment process received signal SIGSEGV
Unexpected internal error: Master process received signal SIGSEGV
```

The word is still `Master` in that one string on 7.x — do not grep for "Coordinator process".

Asserts only exist in a build configured `--enable-cassert`. See
[greengage-build](../greengage-build/SKILL.md).

## Find the crash: gate on the signal, not on the message

Order of operations, every time:

1. **Count crashes** with the reliable gate — the postmaster's own report
   (`src/backend/postmaster/postmaster.c:4262`):
   `grep -ac "was terminated by signal" <all csv>`
2. **Name them** from the assert/PANIC lines. If the signal count is non-zero and your
   assert grep is empty, **your pattern is wrong, not the logs** (see the grep-class trap
   in [reference/reading-logs.md](reference/reading-logs.md)).
3. **Take the statement** from the postmaster's detail line,
   `Failed process was running: <SQL>`. It is truncated at 1024 bytes
   (`activity_buffer[1024]`, `postmaster.c:4227`) and is empty when `track_activities` is
   off — a long query comes back cut, so re-derive the tail from the client side.
4. **Narrow to a minimal query** and confirm it still crashes on a clean cluster.

Signal → meaning: `6` = `abort()` (assert or PANIC), `11` = SIGSEGV, `7` = SIGBUS,
`9` = something outside the server (OOM killer, your own `pkill`).

Where the logs are, the 30-column CSV layout, the failure-signature table and the
QD↔QE correlation method: **[reference/reading-logs.md](reference/reading-logs.md)**.
Read it before triaging any crash or any red suite.

## Reproduce reliably

- **Match the exact shape.** Column types, `GROUP BY`, `FILTER`, `DISTINCT`, join order,
  and `optimizer=on`/`off` each select a different code path. GPORCA and the Postgres
  planner produce different plans and crash in different places, so always record which
  one produced the crash (`SHOW optimizer;`) and reproduce under the same setting.
- **Match the build flags.** `--enable-cassert` turns latent corruption into a loud
  assert; without it the same query returns wrong data silently. `--disable-orca` removes
  a whole optimizer. See [greengage-build](../greengage-build/SKILL.md).
- **base64 the SQL when it crosses a shell boundary.** Building SQL inside
  `docker exec ... bash -lc '...'` or `su - gpadmin -c '...'` eats inner single quotes and
  expands `$` inside `$tag$` dollar-quoting. Write the `.sql` on the host, then:

  ```bash
  B64=$(base64 -w0 repro.sql)
  docker exec -e B64="$B64" <container> su - gpadmin -c \
    'echo "$B64" | base64 -d > /tmp/repro.sql; psql -d regression -f /tmp/repro.sql'
  ```

  This is the only transport that survives nesting intact.

## Before you "fix" anything: three misdiagnosis guards

### 1. Is the PANIC intentional?

Some PANICs are designed behaviour that a test asserts. Search `src/test/` for a test that
*validates* the exact string before you suppress it.

Grounded example: a mirror that hits `WAL contains references to invalid pages`
(`src/backend/access/transam/xlogutils.c:98,245`) while replaying an append-optimized
truncate record for a missing/unwritable file is **designed self-heal** — the mirror goes
down and is rebuilt from the primary. `src/test/regress/sql/mirror_replay.sql` provokes
exactly this (it chmods the mirror's relfile read-only, VACUUMs, then waits for
`gp_segment_configuration.status = 'd'` and recovers with `gprecoverseg -aF`), and it is
in the schedule at `src/test/regress/greengage_schedule:318`. A "fix" that suppresses that
PANIC breaks the test.

The same applies to every `gp_inject_fault(..., 'panic', ...)` in `src/test/isolation2/sql/` —
those crashes are the assertion, not the bug.

### 2. Is the state contaminated?

A fault left armed by an interrupted earlier run makes every later run lie: a `suspend`
fault reads as an infinite hang, an `error` fault reads as a spurious ERROR. Faults live in
each postmaster's shared memory and survive until reset or restart — nothing clears them at
end of test. Before believing a new bug:

```sql
SELECT gp_inject_fault_infinite('all', 'reset', dbid) FROM gp_segment_configuration WHERE status='u';
```

(`all` is `FaultInjectorNameAll`, `src/include/utils/faultinjector.h:24`; this exact statement is
what the behave harness runs after every `gpstate`-tagged scenario,
`gpMgmt/test/behave/mgmt_utils/environment.py:205`.)
Then restart or recreate the cluster ([greengage-cluster-ops](../greengage-cluster-ops/SKILL.md))
and re-observe. Crash debris and in-doubt 2PC transactions contaminate the same way.

### 3. Is the binary stale?

A committed fix that is not in the running `postgres` produces a perfectly reproducible
"the fix does not work". Verify the live binary before trusting any result —
[greengage-build](../greengage-build/SKILL.md) has the detection and the deploy recipe.

## `gp_debug_linger`: catch the backend before it dies

Greengage will hold a backend open after a fatal internal error specifically so you can
attach a debugger (`src/backend/utils/error/elog.c:574-578`, `elog.c:4868-4915`). It fires for any
`FATAL` with `ERRCODE_INTERNAL_ERROR` — which is exactly what an assert failure raises.

```sql
SET gp_debug_linger = 300;   -- seconds, max 3600
-- run the crashing statement; the backend logs and then waits
```

The log carries the hint you need:

```
Process 41287 will wait for gp_debug_linger=300 seconds before termination.
Note that its locks and other resources will not be released until then.
```

and the lingering process advertises itself in `ps`: its title ends with
`error exit in 4m 58s`. Attach gdb to that pid while it waits.

| | 7.x | 6.x |
|---|---|---|
| `gp_debug_linger` default | `0` (off) — `guc_gp.c:3650-3658` | `120` in `--enable-cassert` builds, `0` otherwise — `guc_gp.c:4055-4074`, split by `#ifdef USE_ASSERT_CHECKING` |

The 6.x default is a trap in the other direction: on a 6.x assert build, every asserting
backend holds its locks for two minutes, so a crashing test looks like a cluster-wide
hang. `SET gp_debug_linger = 0;` when you want fast failure.

`gp_debug_linger` does **not** cover SIGSEGV. That path never reaches `errfinish` at all:
the SEGV/BUS/ILL handler writes a pre-built chunk straight to the syslogger pipe and then
`raise()`s the signal unconditionally to produce a core (`elog.c:5024-5097`). For segfaults,
use a core file (see [reference/reading-logs.md](reference/reading-logs.md)).

## Fault injection makes a race deterministic

`gpcontrib/gp_inject_fault` arms a named fault point in one segment's shared memory. 192
distinct `SIMPLE_FAULT_INJECTOR()` points exist on 7.x (187 on 6.x), plus the
`FaultInjector_InjectFaultIfSet*` variants that filter by DDL statement, database, table or
transaction nesting level.

**It is only built with `--enable-debug-extensions`** (`gpcontrib/Makefile`). That is the
default on 7.x and **not** the default on 6.x — a plain 6.x `./configure` build fails with:

```
ERROR:  could not open extension control file ".../extension/gp_inject_fault.control": No such file or directory
```

Fix by rebuilding with `--enable-debug-extensions` (or, on 6.x, `make devel -C gpAux`,
which passes it). The same flag is what defines `FAULT_INJECTOR` and therefore compiles the
`SIMPLE_FAULT_INJECTOR()` macros into anything at all (`src/include/utils/faultinjector.h:152-159`).

`CREATE EXTENSION gp_inject_fault;` is needed **once per database** — it is not global.

Fault types, verbatim from the `FI_TYPE` list in `src/include/utils/faultinjector_lists.h`
(that list is identical on 6.x and 7.x; the `FI_DDL_STATEMENT` list in the same file is not):

| Type | Effect |
|---|---|
| `sleep` | sleep `extra_arg` seconds |
| `fatal` / `panic` / `error` | `elog()` at that level. `fatal` and `panic` call `AvoidCorefileGeneration()` first, so they leave **no core** |
| `infinite_loop` | loop until query cancel or terminate |
| `suspend` | block until the fault is reset or set to `resume`. On 7.x the wait loop calls `CHECK_FOR_INTERRUPTS()` (`src/backend/utils/misc/faultinjector.c:549`) so a query cancel breaks it; **on 6.x it does not** (same file, `:422-426`) — there, only a reset frees the backend |
| `resume` | release backends blocked on a `suspend` |
| `skip` | no action; the C code branches on `== FaultInjectorTypeSkip` |
| `segv` | crash the backend with SIGSEGV — also preceded by `AvoidCorefileGeneration()`, so **no core** |
| `interrupt` | make the next interrupt cycle cancel the query |
| `finish_pending` | set `QueryFinishPending` |
| `exit_no_callbacks` | `_exit(extra_arg)` — no cleanup |
| `wait_until_triggered` | block the *caller* until the fault has fired N times |
| `reset` | remove the fault |
| `status` | report hit count and state (`set` / `triggered` / `completed`) |

The canonical suspend / wait / reset pattern (`src/test/isolation2/sql/analyze_progress.sql:7-17`):

```sql
-- arm on every primary, firing on the 20th hit only
SELECT gp_inject_fault('analyze_block', 'suspend', '', '', '', 20, 20, 0, dbid)
  FROM gp_segment_configuration WHERE content > -1 AND role = 'p';
1&: ANALYZE t;                              -- background session
SELECT gp_wait_until_triggered_fault('analyze_block', 1, dbid)
  FROM gp_segment_configuration WHERE content > -1 AND role = 'p';
-- ... observe the frozen state ...
SELECT gp_inject_fault('analyze_block', 'reset', dbid)
  FROM gp_segment_configuration WHERE content > -1 AND role = 'p';
```

Rules that are not optional:

- **Target by `dbid`, not `content`.** The function looks the row up in
  `gp_segment_configuration` and opens a **direct libpq connection** to that host:port
  (`gpcontrib/gp_inject_fault/gp_inject_fault.c:129-134`); a wrong dbid gives
  `ERROR: dbid %d not found` (`:81`) or `connection to dbid %d %s:%d failed` (`:134`).
- **Reset a fault before re-injecting it with different parameters.** The entry is keyed by
  name; re-arming an existing name is refused with
  `could not insert fault injection, entry already exists` (`faultinjector.c:789-798`).
- **At most 15 faults can be armed per segment.** `FAULTINJECTOR_MAX_SLOTS` is 16 and the
  check is `numActiveFaults + 1 >= 16` (`faultinjector.c:758`); the 16th returns
  `could not insert fault injection, max slots:'16' reached`.
- **Disable FTS before injecting a `panic`.** The extension warns you itself:
  `consider disabling FTS probes while injecting a panic.` with hint
  `Inject an infinite 'skip' into the 'fts_probe' fault to disable FTS probing.`
  (`gp_inject_fault.c:23-32`). In practice:
  `SELECT gp_inject_fault_infinite('fts_probe', 'skip', 1);` (dbid 1 is the coordinator),
  and reset it afterwards — otherwise FTS marks the panicking segment down and fails over
  mid-experiment.
- **Always reset.** A leftover fault is guard 2 above.

Find fault points and worked examples:

```bash
# the 192 distinct names on 7.x - note the character class, see reading-logs.md
git grep -oh 'SIMPLE_FAULT_INJECTOR("[a-zA-Z_0-9]*")' -- src/backend | sort -u
git grep -n 'FaultInjector_InjectFaultIfSet' -- src/backend   # the filtered variants
git grep -ln gp_inject_fault -- src/test/isolation2/sql       # 102 tests using them
```

## Temporary `elog`: LOG lands on the segment, NOTICE reaches your psql

`elog(LOG, ...)` from a QE is written **only to that segment's own CSV log** — it never
reaches the QD. If you want the value at the psql prompt, use `NOTICE`/`WARNING`: the
dispatcher relays QE notices to the client and stamps them with the origin
(`MPPnoticeReceiver`, `src/backend/cdb/dispatcher/cdbconn.c:556`), so you get

```
NOTICE:  DBG nvalid=3 relname=pg_temp_16401  (seg0 slice1 127.0.1.1:7002 pid=26472)
```

Rebuild ([greengage-build](../greengage-build/SKILL.md)), run, read it back. Then
**remove every instrumentation hunk before committing** and confirm `git diff` is exactly
the fix.

A backtrace is already free: every `ereport` at `ERROR` or above captures 30 frames
(`elog.c:466`) and the CSV `logstack` column carries the symbolized frames. Turn on
`SET gp_log_stack_trace_lines = on;` (default `off`) to have Greengage shell out to
`addr2line -s -e <postgres>` and print `file:line` per frame instead of `symbol + 0xNN`.

## gdb on a live backend

**Getting ptrace inside the CI containers.** `ci/readme.md` states it outright:
*"To use gdb inside the container, add the `--privileged` flag to the run command."*
`--cap-add=SYS_PTRACE --security-opt seccomp=unconfined` is the narrower equivalent.
Without a container rebuild, go through the host:

```bash
cpid=$(docker inspect <container> --format '{{.State.Pid}}')
sudo nsenter -t "$cpid" -p -m gdb -p <pid-inside-container> -batch -ex bt
```

**Finding the right process.** Segment backends are forked per query and die with it. The
process title is built in `src/backend/utils/misc/ps_status.c:352-416` as

```
postgres:  7002, gpadmin regression 127.0.1.1(41234) con8 seg0 cmd3 slice1 SELECT
```

`con<N>` is `gp_session_id`, `seg<M>` the content id, `slice<S>` the plan slice. Filter
candidates by **database name** so you never touch another suite's backend.

Two ways to make a short-lived QE stand still: `SET gp_debug_linger` (above), or park an
existing gang. `pg_sleep` alone creates nothing — run one distributed statement first
(`SELECT count(*) FROM <any distributed table>;`) so a gang exists, then `SELECT pg_sleep(45);`
and read the pids while it runs. The idle-gang reaper only arms when the session goes idle
waiting on the client (`postgres.c:5346`), so it will not fire during the sleep — but leave
the psql prompt idle longer than `gp_vmem_idle_resource_timeout` (default **18 s**; 600 s on
`--enable-cassert` builds) and the gang is torn down and the pids change.

**Safety rules:**

- **Never attach while a regression suite is running.** Freezing a suite's QE can trigger a
  shared-memory reset that poisons unrelated tests, and the failures look like real bugs.
- Resume anything you stopped before killing it:
  `ps -eo pid,stat,comm | awk '$2~/T/ && $3~/postgres/{print $1}' | xargs -r kill -CONT`.
- Kill helpers by exact name (`pkill -9 -x gdb`, `pkill -9 -x psql`). `pkill -f <pattern>`
  matches your own shell's command line and kills your script.
- A release build keeps function names but not DWARF: backtraces resolve, struct fields do
  not. Read them from the argument registers by offset, or rebuild with `--enable-debug`.

## Hangs: nothing breaks a cross-segment deadlock by default

`gp_enable_global_deadlock_detector` is **`false` by default on both 6.x and 7.x**
(`guc_gp.c`, `PGC_POSTMASTER`). A deadlock whose cycle spans two segments is therefore not
detected at all — the statement waits forever. When the detector is on, it runs every
`gp_global_deadlock_detector_period` seconds (default **120**), so even then the "hang"
lasts up to two minutes before `global deadlock detected! Final graph is :...` appears
(`src/backend/utils/gdd/gddbackend.c:227`).

Distinguish hang from slow by asking both tiers what they are waiting on:

```sql
-- 7.x: wait_event_type / wait_event exist (PostgreSQL 12 base)
SELECT sess_id, pid, wait_event_type, wait_event, state, query FROM pg_stat_activity;
SELECT gp_segment_id, pid, wait_event_type, wait_event, query
  FROM gp_dist_random('pg_stat_activity') WHERE state <> 'idle';
```

**6.x delta:** `pg_stat_activity` there has no `wait_event`/`wait_event_type`/`backend_type`.
It has `waiting` (boolean) and `waiting_reason` instead
(`src/backend/catalog/system_views.sql`). Same for `gp_dist_random('pg_stat_activity')`.

For statistical wait analysis on 7.x there is `gg_wait_sampling`, a Greengage extension
(no 6.x equivalent). It needs `shared_preload_libraries` and a restart, then exposes
cluster-wide `gg_wait_sampling_current`, `_history` and `_profile` views built as unions of
the coordinator-local and segment-local functions. **Every object lives in the
`gg_wait_sampling` schema** — schema-qualify or extend `search_path`
(`gpcontrib/gg_wait_sampling/README.md`).

A suspended fault injector looks identical to a hang. Check guard 2 first.

## Blast-radius triage

One root cause routinely produces dozens of `regression.diffs` hunks: a crash fails every
test running in the same parallel group, not just the one that provoked it.

- **Count distinct asserts, not failed tests.** Deduplicate by `File: "<x>.c", Line: <n>`
  before claiming "N crashers".
- **Group failures by the shared error string**, fix that one cause, re-measure.
- A QE crash shows up in three places at once: the crashed segment's log has the
  assert/PANIC and its own `terminated by signal`, the QD log has the resulting
  `interconnect encountered a network error, please check your network` or
  `interconnect error: connection closed prematurely`, and later tests fail with
  `failed to acquire resources on one or more segments` /
  `Segments are in reset/recovery mode.` Only the first is the bug.

## What not to do

- Do not grep for `TRAP:`, `ProcSignalBarrier`, or `backtrace_functions` — none of them
  exist in Greengage 7.x (PostgreSQL 12.22).
- Do not diagnose from `regression.diffs` counts. Diff counts measure the blast radius,
  not the number of bugs.
- Do not trust a run whose logs you did not isolate. `gpstop` rewrites file mtimes, so old
  `.csv` files look fresh; see the one-run isolation protocol in
  [reference/reading-logs.md](reference/reading-logs.md).
- Do not leave a fault armed, a `gp_debug_linger` set, a `core_pattern` overridden, or an
  `elog` in the tree.
- Do not conclude "the mirror is broken" from a mirror PANIC without checking whether a
  test provokes it deliberately.

See also: [reference/reading-logs.md](reference/reading-logs.md) (log locations, CSV
columns, failure signatures, QD↔QE correlation, cores),
[greengage-build](../greengage-build/SKILL.md) (assert builds, debug-extensions, proving
the binary is fresh), [greengage-testing](../greengage-testing/SKILL.md) (running one test,
isolation2 fault-injection tests), [greengage-cluster-ops](../greengage-cluster-ops/SKILL.md)
(restarting, recovering segments, clearing crash debris),
[greengage-internals](../greengage-internals/SKILL.md) (what the crashing code does),
[greengage-ci](../greengage-ci/SKILL.md) (getting logs out of a failed CI job).
