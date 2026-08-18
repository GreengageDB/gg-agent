# Masking inventory — what is already normalised, and where

Lookup material for [greengage-answer-files](../SKILL.md). Everything here was read
from `refs/remotes/origin/7.x` of `GreengageDB/greengage`. Before you add a mask,
check whether it already exists in this inventory — most environment noise is
already handled.

## Where masks live

| File | Applies to | Wired in by |
|---|---|---|
| `src/test/regress/init_file` | **every** regress test, and every isolation2 suite | `REGRESS_OPTS = ... --init-file=$(srcdir)/init_file` (`src/test/regress/GNUmakefile:215`) |
| `src/test/isolation2/init_file_isolation2` | isolation2 default, mirrorless, hot-standby, ic-tcp, ic-proxy, resource-queue | `--init-file=./init_file_isolation2` (`src/test/isolation2/Makefile`) |
| `src/test/isolation2/init_file_resgroup` | `installcheck-resgroup`, `installcheck-resgroup-v2` | `--init-file=./init_file_resgroup` |
| `src/test/isolation2/init_file_parallel_retrieve_cursor` | `installcheck-parallel-retrieve-cursor` | `--init-file=./init_file_parallel_retrieve_cursor` |
| `<results>.initfile` | only the one isolation2 test it was generated for, at run time | `sql_isolation_testcase.py:127`, from `${MATCHSUBS}` built by the `create_match_sub` / `parse_endpoint_info` helpers in `global_sh_executor.sh`, called from `@post_run` hooks |
| `-- start_matchsubs` / `-- start_matchignore` in `sql/<t>.sql` | that one test | atmsort parses the echoed block out of the results stream |
| `atmsort.pm` `init_match_subs()` / `init_matchignores()` | everything, unconditionally | compiled in, no file to edit |

Every isolation2 target passes **both** `src/test/regress/init_file` and its own
init file. There is one `atmsort.pm`; `src/test/isolation2/Makefile` symlinks
`gpdiff.pl`, `gpstringsubs.pl`, `GPTest.pm`, `atmsort.pm` and `explain.pm` from
`../regress/`.

## atmsort built-in defaults (`atmsort.pm`, no file to edit)

Matchsubs (`init_match_subs`, line 216):

```
m/\s+\(seg.*pid.*\)/
s/\s+\(seg.*pid.*\)//

m/^(?:ERROR|WARNING|CONTEXT|NOTICE):.*connection.*failed.*(?:http|gpfdist)/
s/connection.*failed.*(http|gpfdist).*/connection failed dummy_protocol\:\/\/DUMMY_LOCATION/
```

Matchignores (`init_matchignores`, line 337):

```
m/^NOTICE:  dropping a column that is part of the distribution policy/
m/^NOTICE:  table has parent\, setting distribution columns to match parent table/
m/^WARNING:  referential integrity \(.*\) constraints are not supported in Greengage Database/
m/^NOTICE:  \w+ \".*\" does not exist\, skipping\s*$/
```

Plus, not expressible as a pattern:

- Adjacent duplicate `NOTICE|ERROR|HINT|DETAIL|WARNING` lines that are identical
  after `(seg… pid=…)` stripping collapse to one (`atmsort.pm:1282-1320`). N
  segments raising the same error print once.
- The `(N rows)` trailer after an EXPLAIN is prefixed `GP_IGNORE:` (`atmsort.pm:1151-1157`).
- The ` QUERY PLAN ` header line and its `-----` rule are rewritten to `QUERY PLAN`
  and `___________` inside any block atmsort classified as an EXPLAIN
  (`atmsort.pm:1369-1376`; present on 6.x and 7.x).
- Costed EXPLAIN output goes through `explain.pm` with `PRUNE => 'heavily'`
  (`atmsort.pm:491-496`), which re-emits the plan as a node tree. That **drops** the
  per-node detail lines (`Sort Key:`, `Filter:`, `Hash Cond:` — only each node's
  first line survives), the per-node `total_time`/`to_first`/`to_end`, and the
  `Slice statistics:` … `Settings:` … `Total runtime:` trailer (`explain.pm:920-938`,
  `explain.pm:1182`). It does **not** drop `(cost=… rows=… width=…)`,
  `(actual time=…)` or `(slice1; segments: 3)` — `prune_heavily`
  (`explain.pm:1262`) copies slice/gang/segment numbers into separate keys but
  leaves the node text intact. Tests that need those masked ship their own
  matchsubs; see `sql/direct_dispatch.sql:1-7`.

## `src/test/regress/init_file` — matchignore inventory

Bare `m/…/` patterns; a matching line is dropped from **both** sides.

| Pattern (abridged) | Kills |
|---|---|
| `m/^NOTICE:  extension "gp_inject_fault" already exists, skipping/` | idempotent `CREATE EXTENSION` in fault-injection tests |
| same for `gp_debug_numsegments`, `postgres_fdw` | ditto |
| `m/^ Optimizer status:.*/`, `m/^ Optimizer: GPORCA/`, `m/^ Optimizer: Postgres-based planner/`, `m/^ Optimizer: Pivotal Optimizer \(GPORCA\).*/`, `m/^ Optimizer: Postgres query optimizer/` | the EXPLAIN optimizer line — **so an answer file cannot assert which optimizer ran** |
| `m/^ Settings:.*/` | the whole EXPLAIN `Settings:` line, JIT GUCs included |
| `m/^(?:HINT\|NOTICE):\s+.+\'DISTRIBUTED BY\' clause.*/` | every "Table doesn't have 'DISTRIBUTED BY' clause" NOTICE and its HINT |
| `m/^NOTICE:.*CREATE TABLE will create partition ".*" for table ".*"/` | anonymous partition names (`hhh_1_prt_r1987544232`) |
| `m/^NOTICE:.*resource queue required -- using default resource queue ".*"/` | role-creation resource-queue NOTICE |
| `m/^NOTICE:.*building index for child partition ".*"/` | per-child index NOTICEs, which arrive in random order |
| `m/^NOTICE:.*exchanged partition ".*" with relation ".*"/` | `pg_temp_NNNN` names from partition split/exchange |
| `m/^WARNING:  could not close temporary file .*: No such file or directory/` | |
| `m/^WARNING:  resource queue is disabled$/`, `m/^HINT:  To enable set gp_resource_manager=queue$/`, `m/^NOTICE:  resource group required -- using .* resource group ".*"$/` | the queue-vs-group manager difference |
| `m/^WARNING:  table ".*" contains rows in segment .*, which is outside the # of segments for the table's policy \(\d+ segments\)$/` | inherited tables with a wider `numsegments` |
| `m/Distributed by: \(.*\)/`, `m/Distributed randomly/` | **`\d` distribution output — you cannot regression-test it** |
| `m/WARNING:  interconnect may encountered a network error, please check your network/`, `m/Failing to send packet/` | UDP interconnect noise |
| `m/^DEBUG:  successfully loaded JIT provider/` and three sibling `DEBUG: …JIT…` lines | JIT-on vs JIT-off drift |
| `m/^WARNING:  creating a table with no columns./` | |
| `m/NOTICE:  specifying ".*" acts as no operation./` | data-access indicator |
| `m/FATAL:  terminating connection due to administrator command/` | not always echoed to the client |

## `src/test/regress/init_file` — matchsubs inventory

Paired `m/…/` then `s/…/…/`. Applied to both sides where the match hits.

| Masks | Replacement |
|---|---|
| `\s+\(entry db(.*)+\spid=\d+\)` | deleted (the coordinator twin of atmsort's `(seg… pid=…)` rule) |
| `overlaps existing partition "r\d+"` | `partition "r##########"` |
| `Table "pg_temp_\d+.temp` | `Table "pg_temp_#####` |
| `Hash Cond: \(pg_temp_\d+` | `Hash Cond: \(pg_temp_#####` |
| `\d+ was concurrently dropped` | `##### was concurrently dropped` |
| `ERROR:  ANALYZE cannot merge …`, `Cannot run ANALYZE MERGE …` | `(analyze.c:XXX)` |
| `ERROR:  invalid partition constraint on "…"` | `(cdbpartition.c:XXX)` |
| `ERROR:  FIPS enabled OpenSSL is required …`, `requested functionality not allowed in FIPS mode …` | `(openssl.c:XXX)` |
| `ERROR:  could not devise a plan.*` | `(cdbpath.c:XXX)` |
| `ERROR:  Cannot use "md5": No such hash algorithm` / `… Some PX error (not specified)` | `ERROR:  Cannot use "md5": ` (OpenSSL version drift) |
| `One-Time Filter: \(gp_execution_segment\(\) = \d+` | `= ###` |
| `ERROR:  infinite recursion detected.*` | truncated to the bare message |
| `ERROR:  could not find hash function for hash operator.*` | truncated |
| `nodename nor servname provided, or not known` | `Name or service not known` (macOS vs Linux resolver) |
| `ERROR:  could not devise a query plan for the given query \(.*\)` | truncated |
| `ERROR:  could not pull up equivalence class using projected target list \(.*\)` | truncated |
| `^DETAIL:.*gid=.*` | `gid DUMMY` |
| the "do not have statistics" NOTICE and its HINT | deleted (`s/.//gs`) |
| `\(dbsize\.c:\d+\)`, `\(cdbmutate\.c:\d+\)` | `:XXX` |
| ` \(cdbdisp_async\.c.*\)`, ` \(parse_utilcmd\.c:\d+\)` | deleted |
| `The shortest/longest establish conn time: \d+\.\d+ ms, segindex: \d+` | `xx.xx ms, segindex: xx` |
| `^\s+QUERY PLAN\s*$` | ` QUERY PLAN ` — **7.x only**, normalises the header width so the same answer file survives different `PGOPTIONS`. A backstop: atmsort already rewrites the header of anything it recognised as an EXPLAIN |
| `^------------+\s*$` | `------------` — same, for a single-column rule line |
| `resource queue id: \d+` | `resource queue id: XXXX` |

**6.x delta:** `src/test/regress/init_file` on 6.x has no `QUERY PLAN` / rule-line
width matchsub, no `Optimizer: GPORCA` / `Optimizer: Postgres-based planner`
matchignores, and none of the `(dbsize.c:N)` / `(cdbmutate.c:N)` line-number
matchsubs. On 6.x a `QUERY PLAN` header outside a recognised EXPLAIN block is a
real diff; inside one, `atmsort.pm` rewrites it on both lines.

The `Heap Blocks: exact=`/`lossy=` rules are present but **commented out** (each
line prefixed `-- `) in both `init_file` and `init_file_isolation2`. Do not assume
they are active.

## isolation2 masks

`init_file_isolation2` (matchsubs only) additionally covers: `gpconfig` INFO
prefixes, `(cdbgang_async.c:NNN)`, invalid-toast-index OIDs, `FTS detected
connection lost during dispatch to` addresses, `deadlock detected` addresses,
`(slice\d+ IP:PORT pid=N)` and bare `(IP:PORT pid=N)` suffixes, `requested N
bytes`, deadlock `DETAIL: Process N waits for ShareLock on transaction N` lines,
resource-queue deadlock lines, `available N MB`, `(cdbdisp_async.c…)`, and
`pg_waldump` output (`tx:`, `lsn: X/YYYY, prev X/YYYY`, `rel a/b/c`).

`init_file_resgroup` adds matchignores for `^CONTEXT:  SQL function ".+"
statement \d+$` and `^ERROR:  Canceling query because of high VMEM .+`, plus
matchsubs for cgroup-misconfiguration messages, `Out of memory (seg… pid=…)`,
and `role with Oid \d+ was dropped`.

## Per-test directives atmsort understands

Written as SQL comments in `sql/<t>.sql`; psql echoes them, so they appear in the
answer file too and must be present in **every** variant of it.

| Directive | Effect | Parsed at |
|---|---|---|
| `-- start_ignore` … `-- end_ignore` | every line in between is prefixed `GP_IGNORE:` and dropped by `diff -I GP_IGNORE:`. Nests. | `atmsort.pm:1186`, `:1072` |
| `-- start_matchsubs` … `-- end_matchsubs` | paired `-- m/…/` + `-- s/…/…/` lines; leading `-- ` is stripped before compiling | `atmsort.pm:1180` |
| `-- start_matchignore` … `-- end_matchignore` | bare `-- m/…/` lines | `atmsort.pm:1180` |
| `-- ignore` | ignores the output of the next statement only | `atmsort.pm:1227` |
| `-- order 1` / `-- order 1, 2` | sort the result by those **column numbers** (not names) | `atmsort.pm:1227` |
| `-- order none` | never sort, even without ORDER BY | `atmsort.pm:1241` |
| `-- mvd <spec>` | multi-valued-dependency sort | `atmsort.pm:1267` |
| `-- force_explain` / `-- force_explain operator` | treat the next output as an EXPLAIN plan | `atmsort.pm:1248` |
| `-- explain_processing_off` / `_on` | disable/enable explain.pm canonicalisation | `atmsort.pm:1259` |

Usage on 7.x: `-- order 1` in 49 places, `-- force_explain` 24, `-- start_ignore`
in 162 `sql/` files, `-- start_matchsubs` in 104.

## Whole-run switches

| Switch | Reaches | Effect |
|---|---|---|
| `pg_regress --ignore-plans` | `gpdiff.pl -gpd_ignore_plans` | ignores **all** plan content, `EXPLAIN (COSTS OFF)` included. A blunt instrument; never commit an answer file validated only under it. |
| `pg_regress --init-file=F` | `gpdiff.pl --gpd_init F` | repeatable |
| `ignore: <test>` line in a schedule | pg_regress | test still runs and still writes its diff, prints `failed (ignored)` and is counted separately from `fail_count`, so it does not set the non-zero exit status (`pg_regress.c:2372`). Three in the schedules `installcheck-good` runs: `gp_portal_error`, `tpch500GB_orca` (greengage_schedule), `random` (parallel_schedule); five more in `serial_schedule`, one in `icudp_schedule`, four lines in `isolation2_schedule`. |
