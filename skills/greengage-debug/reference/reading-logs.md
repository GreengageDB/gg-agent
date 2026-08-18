# Reading Greengage logs

Lookup material for triaging a crash, an assert or a hang on a gpdemo cluster.
Method lives in [SKILL.md](../SKILL.md).

## Where the logs are

The log directory *is* `log_directory`, despite the GUC's inherited description string
`Defunct: Sets the destination directory for log files.` — the syslogger really reads it
(`syslogger.c:841` creates it, `:378` names the file, `:451-457` re-rotates on SIGHUP).
What differs between the lines is the default:

| | 7.x | 6.x |
|---|---|---|
| `log_directory` default (`guc.c`) | `log` | `pg_log` |
| Server log dir | `<datadir>/log/` | `<datadir>/pg_log/` |
| `log_filename` default | `gpdb-%Y-%m-%d_%H%M%S.csv` | same |
| `pg_ctl` startup output | `<datadir>/log/startup.log` | `<datadir>/pg_log/startup.log` |

On 7.x an **absolute** `log_directory` additionally gets `/<dbid>` appended, so segments
never collide (`check_log_directory`, `guc.c:11653-11673`); a relative value is used as is.

`gp_log_format` is an enum (`text`, `csv`) defaulting to `csv` (`guc_gp.c:4774-4781`,
`gp_log_format_options`). `gp_log_format=text` renames the file to `.log`
(`syslogger.c:2431-2438`) and loses every Greengage column below.

Demo-cluster layout, from `gpAux/gpdemo/demo_cluster.sh`
(`QDDIR=$DATADIRS/qddir`, `SEG_PREFIX=demoDataDir`, `STANDBYDIR=$DATADIRS/standby`,
`PRIMARY_DIR=$DATADIRS/dbfast$i`, `MIRROR_DIR=$DATADIRS/dbfast_mirror$i`), with
`DATADIRS` defaulting to `gpAux/gpdemo/datadirs`:

| Process | Datadir | Log (7.x) |
|---|---|---|
| Coordinator (QD), content −1 | `gpAux/gpdemo/datadirs/qddir/demoDataDir-1/` | `log/gpdb-*.csv` |
| Primary content N | `gpAux/gpdemo/datadirs/dbfast<N+1>/demoDataDir<N>/` | `log/gpdb-*.csv` |
| Mirror content N | `gpAux/gpdemo/datadirs/dbfast_mirror<N+1>/demoDataDir<N>/` | `log/gpdb-*.csv` |
| Standby coordinator | `gpAux/gpdemo/datadirs/standby/` | `log/gpdb-*.csv` |
| `gpinitsystem` and friends | — | `gpAux/gpdemo/datadirs/gpAdminLogs/` |
| Any other `gp*` utility run | — | `~/gpAdminLogs/<utility>_<YYYYMMDD>.log` |

(`demo_cluster.sh` passes `-l $DATADIRS/gpAdminLogs` to `gpinitsystem`; everything else
falls back to `~/gpAdminLogs`, `gpMgmt/bin/gppylib/gplog.py:283-302`.)

Sweep everything at once:

```bash
grep -a "FailedAssertion\|terminated by signal\|PANIC" \
    gpAux/gpdemo/datadirs/*/demoDataDir*/log/gpdb-*.csv \
    gpAux/gpdemo/datadirs/standby/log/gpdb-*.csv
```

On 6.x replace every `log/` with `pg_log/`.

## `gplogfilter` beats `grep` on CSV

A CSV record spans multiple physical lines (quoted fields contain newlines), so `grep`
returns fragments. `gplogfilter` parses `.csv` input with a real CSV reader
(`gpMgmt/bin/gplogfilter:257-258`) and reassembles records:

```bash
gplogfilter -t <file.csv>                    # only ERROR / FATAL / PANIC entries
gplogfilter -m 'FailedAssertion' <file.csv>  # regex over the whole record
gplogfilter -b '2026-08-18 13:00' -e '2026-08-18 13:05' <file.csv>
gplogfilter -n 50 <file.csv>                 # last 50 entries
```

With no file argument it reads `$COORDINATOR_DATA_DIRECTORY/log/*` on 7.x and
`$MASTER_DATA_DIRECTORY/pg_log/*` on 6.x — the coordinator only, never the segments.
It aborts with `ERROR: Cannot import modules. Please check that you have sourced
greengage_path.sh.` if the environment is not set up.

## The 30-column CSV layout

Greengage's CSV is **not** upstream `csvlog`. The authoritative column list is the
external-table definition behind the `gp_toolkit` log views; the writer is
`syslogger_write_errordata()` (`src/backend/postmaster/syslogger.c:1455-1534`).

- **7.x:** `gp_toolkit` is an extension (`default_version = '1.9'`, `schema = gp_toolkit`).
  `CREATE EXTENSION` runs the `gpcontrib/gp_toolkit/gp_toolkit--1.3.sql` base script plus the
  `--1.3--1.4` … `--1.8--1.9` upgrades; the log block there is byte-identical to
  `gp_toolkit--1.0.sql` and no upgrade script touches it.
- **6.x:** `gp_toolkit` is `src/backend/catalog/gp_toolkit.sql`, loaded by initdb.

| # | Column | Written as | Notes |
|---|---|---|---|
| 1 | `logtime` | `2026-08-18 13:28:01.500984 UTC` | time-window correlation |
| 2 | `loguser` | `"gpadmin"` | |
| 3 | `logdatabase` | `"regression"` | which suite/db |
| 4 | `logpid` | `p643130` | note the `p` prefix |
| 5 | `logthread` | `th` + a signed int32 | `(int32) pthread_self()` (`elog.c:3914`), so a large arbitrary number — **not** `th0`. `th0` appears only on the SIGSEGV lines (`syslogger.c:1547`) |
| 6 | `loghost` | `"127.0.1.1"` | |
| 7 | `logport` | `"41234"` | |
| 8 | `logsessiontime` | timestamp | |
| 9 | `logtransaction` | top xid | written unconditionally (`syslogger.c:1478`) — prints `0`, never empty |
| 10 | `logsession` | `con8` | **QD↔QE correlation key** (`gp_session_id`) |
| 11 | `logcmdcount` | `cmd3` | statement number within the session |
| 12 | `logsegment` | `seg-1` = coordinator, `seg0`, `seg1`, … | always present |
| 13 | `logslice` | `slice1` | plan slice; empty for slice 0 |
| 14/15/16 | `logdistxact`/`loglocalxact`/`logsubxact` | `dx7`/`x1234`/`sx1` | empty when 0 |
| 17 | `logseverity` | `"LOG"`, `"ERROR"`, `"FATAL"`, `"PANIC"` | |
| 18 | `logstate` | `"XX000"` | SQLSTATE |
| 19 | `logmessage` | quoted text | |
| 20 | `logdetail` | quoted text | **where `FailedAssertion(...)` lives** |
| 21 | `loghint` | quoted text | |
| 22 | `logquery` | internal query | |
| 23 | `logquerypos` | int | |
| 24 | `logcontext` | quoted text | |
| 25 | `logdebug` | the user's `debug_query_string` | the statement being run |
| 26 | `logcursorpos` | int | |
| 27 | `logfunction` | `"ExceptionalCondition"` | |
| 28 | `logfile` | `"assert.c"` | source file of the elog site |
| 29 | `logline` | `44` | |
| 30 | `logstack` | `Stack trace:` + frames | present on PANIC and on ERROR+ with location |

Parsing traps:

- Fields written with `test0 = true` (`syslogger_write_int32`, `syslogger.c:1293-1298`)
  are **left empty when the value is ≤ 0** — `logsession`, `logcmdcount`, `logslice`,
  `logdistxact`/`loglocalxact`/`logsubxact`, `logquerypos` and `logline`. Postmaster and
  background-worker lines therefore have no `con<N>`; `grep ",con8,"` silently drops them.
  `logtransaction`, `logsegment` and `logcursorpos` pass `test0 = false` and are always
  printed.
- `logsegment` is written unconditionally and is **always `seg<N>`**, never `mir<N>`:
  `gp_is_primary` is hard-coded `'t'` at both call sites (`elog.c:3929`,
  `syslogger.c:1333`). You tell a mirror's log apart by which *file* it is in.
- Quotes inside a quoted field are **doubled** per CSV. An assert therefore appears as
  `File: ""nodeAgg.c""` — a single-quote regex misses it. In-tree example of the doubled
  form: `src/test/isolation2/sql/resource_queue_terminate.sql:75`.
- Messages span multiple physical lines. Use `gplogfilter`, or `grep -a -A40`.

## Reading the logs as tables

With a live cluster, `gp_toolkit` exposes the same files as relations (superuser only):

| View | 7.x | 6.x |
|---|---|---|
| Whole cluster | `gp_toolkit.gp_log_system` | same |
| Current database only | `gp_toolkit.gp_log_database` | same |
| Coordinator, key columns | `gp_toolkit.gp_log_coordinator_concise` (alias `gp_log_master_concise`) | `gp_toolkit.gp_log_master_concise` |
| First/last timestamp per command | `gp_toolkit.gp_log_command_timings` | same |
| Underlying external tables | `__gp_log_segment_ext`, `__gp_log_coordinator_ext` (alias view `__gp_log_master_ext`) | `__gp_log_segment_ext`, `__gp_log_master_ext` |

```sql
SELECT logtime, logsegment, logslice, logseverity, logmessage, logdetail
  FROM gp_toolkit.gp_log_system
 WHERE logsession = 'con8' AND logseverity IN ('ERROR','FATAL','PANIC')
 ORDER BY logtime;
```

These views `cat` the CSV files through an external web table
(`EXECUTE E'cat $GP_SEG_LOGDIR/*.csv'` on 7.x; `$GP_SEG_DATADIR/pg_log/*.csv` on 6.x), so
they need every segment **up**. After a crash they may be unreadable exactly when you want
them — fall back to the files.

## Failure signatures

Every string below was grepped out of the 7.x tree.

| Signature | Meaning | Next step |
|---|---|---|
| `Unexpected internal error` + `FailedAssertion("…", File: "x.c", Line: N)` | assert failure, FATAL then `abort()` | file:line + `logstack`; needs `--enable-cassert` |
| `Unexpected internal error: Segment process received signal SIGSEGV` | segfault on a QE, logged PANIC with a stack trace | core file / gdb |
| `Unexpected internal error: Master process received signal SIGSEGV` | same on the coordinator (string still says Master on 7.x) | as above |
| `was terminated by signal 6: Aborted` | assert or PANIC reached `abort()` | pair with the FATAL/PANIC line just above |
| `was terminated by signal 11: Segmentation fault` | segfault | core file |
| `Failed process was running: <SQL>` | postmaster names the crashing statement | your repro query; truncated at 1024 bytes |
| `Process N will wait for gp_debug_linger=S seconds before termination.` | a backend is parked for you | attach gdb to N now |
| `interconnect encountered a network error, please check your network` | motion peer vanished | usually secondary to a QE crash elsewhere |
| `interconnect error: connection closed prematurely` | same, but TCP/ic-proxy only (`ic_tcp.c:440`); the default interconnect is UDP | find the crashed QE |
| `failed to acquire resources on one or more segments` | gang creation failed | a segment is down or recovering |
| `Segments are in reset/recovery mode.` | QEs still in post-crash recovery | wait, then find what crashed them |
| `received dbid:N doesn't match this segments configured dbid:M` | FTS probe hit a mis-configured segment | `src/backend/fts/ftsmessagehandler.c:441` |
| `global deadlock detected! Final graph is :…` | GDD broke a cross-segment cycle | only appears if GDD is enabled |
| `could not insert fault injection, max slots:'16' reached` | 15 faults already armed on that segment | reset faults |
| `consider disabling FTS probes while injecting a panic.` | you armed a `panic` fault with FTS live | skip `fts_probe` first |
| `Cluster validation failed:` (pg_regress stderr, not the log) | pg_regress ran **nothing** | recover the cluster, rerun |

**`Cluster validation failed` in detail.** `cluster_healthy()`
(`src/test/regress/pg_regress.c:3532-3547`) runs
`SELECT * FROM gp_segment_configuration WHERE status = 'd' OR preferred_role != role;`
before each schedule line and before each extra test. A non-empty result prints the banner,
sets `halt_work`, and the schedule loops at `pg_regress.c:3372-3382` stop. The run then
reports `All 0 tests passed.` and exits **0** (`pg_regress.c:3414-3417`). A green zero-test
run is a down segment, not a pass — always read the test count, never just the exit status.

## Assert forensics

1. **The signal count is the gate; the assert grep only names them.**

   ```bash
   grep -ac "was terminated by signal" gpAux/gpdemo/datadirs/*/demoDataDir*/log/*.csv
   grep -oaE 'File: ""[A-Za-z0-9_]+\.c"", Line: [0-9]+' <same files> | sort | uniq -c | sort -rn
   ```

2. **Grep-class trap.** The filename class must be `[A-Za-z0-9_]+`, never `[a-z_]+`. A
   lowercase-only class silently drops every mixed-case or digit-bearing filename
   (`nodeModifyTable.c`, `execMain.c`, `nodeAgg.c`, `md5.c`) and can hide a real crasher
   across whole runs. The same trap bites when enumerating fault points: over
   `src/backend` on 7.x, `SIMPLE_FAULT_INJECTOR("[a-z_0-9]*")` finds **180** names and
   `SIMPLE_FAULT_INJECTOR("[a-zA-Z_0-9]*")` finds **192** — the 12 it drops include
   `AfterTablespaceCreateLockRelease`, `AppendOnlyBlockDirectory_GetEntry_sysscan`,
   `ftsLoop_before_probe`, `doSendStopMessageTCP` and `waitOnOutbound`. **If the signal
   count is non-zero and your pattern matches nothing, the pattern is wrong.**

3. **Read the stack from column 30.** Frames are formatted
   `%-4d %p %s %s + 0x%x` (`src/backend/utils/error/elog.c:3638`), e.g.
   `1    0x55a3f1 postgres ExceptionalCondition + 0x8b`. With
   `SET gp_log_stack_trace_lines = on;` (default `off`) Greengage runs
   `addr2line -s -e <postgres>` and prints `postgres ExceptionalCondition (assert.c:44)`
   instead. Grep for `[A-Za-z_][A-Za-z0-9_]* \+ 0x[0-9a-f]+` — note the **spaces** around
   the `+`.

4. **Count distinct asserts, not failed tests.** One crash fails every test in its parallel
   group. Deduplicate by `File:`/`Line:` before reporting a number.

5. **One-run log isolation.** Every stop and start appends to whatever `.csv` is current
   (`database system is shut down`, `miscinit.c:975`), and each logger holds its file open
   across runs, so one file routinely spans several runs and its mtime tells you nothing
   about which run wrote a given record — never dedupe runs by mtime. Protocol:
   `gpstop -a` → `find gpAux/gpdemo/datadirs -name 'gpdb-*.csv' -delete` → `gpstart -a`
   → run → read everything. A freshly recreated cluster starts with empty logs, so anything
   present is from this run.

6. **The syslogger survives a postmaster crash-reset.** If you deleted the active `.csv`
   while the cluster was running, the logger keeps writing to the unlinked inode. Recover
   it via the open fd: `ps -ef | grep "logger process"`, then read
   `/proc/<logger_pid>/fd/<n>`.

7. **Watch the disk.** Both crash paths are built to leave a core: the SEGV/BUS/ILL handler
   `raise()`s the signal after logging (`elog.c:5096`), and an assert returns from
   `errfinish` via `errFatalReturn(gp_reraise_signal)` (default `true`) so
   `ExceptionalCondition` reaches `abort()` (`assert.c:62`). A core is roughly the crashed
   backend's address space, so a crash loop fills a disk fast. To suppress them while
   hunting:
   `echo "|/bin/true" > /proc/sys/kernel/core_pattern` as root; restore a real pattern when
   you actually want a core.

## Correlating QD and QE

Every backend of one user session logs the same `con<N>` (`gp_session_id`), and the process
title carries it too (`src/backend/utils/misc/ps_status.c:352-416`):

```
postgres:  7002, gpadmin regression 127.0.1.1(41234) con8 seg0 cmd3 slice1 SELECT
```

```sql
SELECT current_setting('gp_session_id');   -- from the repro session itself
```

```bash
grep -ah ",con8," gpAux/gpdemo/datadirs/*/demoDataDir*/log/gpdb-*.csv | sort
```

- `logsegment` says which node wrote the line, `logslice` which part of the plan.
- The `was terminated by signal` report for a QE crash is written by **that segment's own
  postmaster**, so it is in that segment's file. The QD file only holds the resulting
  dispatch/interconnect error. To find the crashed node, grep every segment log for the
  signal line inside the failure's time window.
- Errors and notices raised on a QE are re-emitted by the QD with the origin appended, two
  spaces then parentheses — `MPPnoticeReceiver`/`cdbdispatchresult.c` build it from the
  `PG_DIAG_GP_PROCESS_TAG` field:

  ```
  ERROR:  function not supported on relation  (seg0 slice1 192.168.0.148:7002 pid=674753)
  ```

  (real example: `src/test/regress/expected/alter_table_set_am.out:346`). That suffix alone
  pinpoints the node, the slice and the pid — go to that segment's log for the context.
- `elog(LOG, …)` on a QE never leaves the segment. `NOTICE`/`WARNING`/`INFO`/`DEBUG*` do
  reach the client through the dispatcher.

## Core files

```bash
cat /proc/sys/kernel/core_pattern          # containers inherit the host's pattern
echo "core.%e.%p" > /proc/sys/kernel/core_pattern      # as root, for a real file
# after the crash:
gdb $GPHOME/bin/postgres core.postgres.<pid> -batch -ex bt
```

- A piped pattern (`|/usr/share/apport/apport`, `|/bin/true`) means **no file appears in
  the datadir** no matter how hard you look.
- `ulimit -c unlimited` must be in effect for the postmaster, not just your shell.
- `elog(ERROR)` leaves no core — it is a normal error unwind. Use `gp_debug_linger` or a
  temporary `elog` instead ([SKILL.md](../SKILL.md)).
- An injected `fatal`, `panic` or `segv` fault leaves no core either: each of those three
  arms calls `AvoidCorefileGeneration()` first (`faultinjector.c:494`, `:503`, `:592`),
  which sets the `RLIMIT_CORE` soft limit to 0 (`cdbutil.c:1843-1858`).
- Cores are large — roughly the crashed backend's address space. See trap 7 above.
