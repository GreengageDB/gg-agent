# Answer-file map — paths, selection order, and where results land

Lookup material for [greengage-answer-files](../SKILL.md). Verified against
`refs/remotes/origin/7.x` (and `refs/remotes/origin/6.x` for the deltas) of
`GreengageDB/greengage`.

## Tooling

| File | Role |
|---|---|
| `src/test/regress/gpdiff.pl` | runs `atmsort::run()` on both files, then shells out to plain `diff` with whatever options were passed through |
| `src/test/regress/atmsort.pm` | the normaliser: row sorting, built-in matchsubs/ignores, directive parsing |
| `src/test/regress/atmsort.pl` | standalone CLI wrapper around `atmsort.pm` |
| `src/test/regress/explain.pm` | parses costed EXPLAIN into a plan tree and re-emits it pruned |
| `src/test/regress/explain.pl` | standalone CLI wrapper around `explain.pm` |
| `src/test/regress/gpstringsubs.pl` | substitutes `@gpwhich_<exe>@` tokens with the full path of `<exe>` |
| `src/test/regress/gpsourcify.pl` | the reverse: rewrites a `results/*.out` back into a `.source` file with tokens |
| `src/test/regress/pg_regress.c` | drives everything; `results_differ()` at line 1838 is the comparison |
| `src/test/regress/scan_flaky_fault_injectors.sh` | flags tests that call `gp_inject_fault` while sitting in a parallel schedule group. Globs `*schedule` and `sql input specs` in the current directory, so run it from `src/test/regress` or `src/test/isolation2`. Wired into `all` on 6.x; manual on 7.x |
| `src/test/isolation2/sql_isolation_testcase.py` | the isolation2 session syntax, documented in its own docstring |

`src/test/isolation2/Makefile` symlinks `gpdiff.pl`, `gpstringsubs.pl`, `GPTest.pm`,
`atmsort.pm` and `explain.pm` out of `../regress/`. There is one implementation,
shared by both suites.

`gpdiff.pl`, `atmsort.pl`, `explain.pl` and `gpstringsubs.pl` all `use GPTest`,
which configure generates from `src/test/regress/GPTest.pm.in` and which
`src/test/regress/.gitignore` ignores. In a tree that has not been configured they
die with `Can't locate GPTest.pm in @INC`. (`gpsourcify.pl` does not need it.)

## Expected-file selection, in the order pg_regress tries it

From `get_expectfile()` (`pg_regress.c:1069`) and `results_differ()`
(`pg_regress.c:1838`). `optimizer_enabled` and `resgroup_enabled` are decided
**once per run**, by `SHOW optimizer;` and `SHOW gp_resource_manager;` against the
live cluster (`check_feature_status`, `pg_regress.c:2715`) — not per test.

1. `resultmap` entry matching `<test>:<ext>:<host_platform>` — 7.x has three
   entries, all `float4` on cygwin/mingw/hpux.
2. `expected/<t>_optimizer_resgroup.out` if `optimizer=on` **and**
   `gp_resource_manager=group`. Zero such files exist on 7.x.
3. `expected/<t>_optimizer.out` if `optimizer=on`. 153 files on 7.x.
4. `expected/<t>_resgroup.out` if `gp_resource_manager=group`. 5 files on 7.x:
   `resource_group_cpuset`, `resource_group`, `resource_queue`, `strings`,
   `wrkloadadmin`.
5. `expected/<t>.out` — the base file. 584 of them on 7.x (765 `.out` files in
   `expected/` all told, variants and alternates included).
6. If the chosen file still differs, `expected/<t>_1.out` … `<t>_9.out` are tried
   and the one producing the **fewest diff lines** is used for the pretty diff
   (`get_alternative_expectfile`, `pg_regress.c:1771`). 23 such files on 7.x,
   including `select_views_optimizer_1.out` — an alternate of an `_optimizer`
   variant.

Counts: 6.x has 635 `.out` and 106 `_optimizer.out`; isolation2 on 7.x has 249
`.out` and 9 `_optimizer.out`. The alternates loop runs `i = 0 … 9`, so `<t>_0.out`
would be picked up too — no test ships one.

## Diff options actually used

`pg_regress.c:76-77`, non-Windows:

```
basic_diff_opts  = "-I HINT: -I CONTEXT: -I GP_IGNORE:"
pretty_diff_opts = "-I HINT: -I CONTEXT: -I GP_IGNORE: -U3"
```

There is **no `-w`** outside Windows. Whitespace, including trailing whitespace
and column padding, is significant. `PG_REGRESS_DIFF_OPTS` overrides
`pretty_diff_opts` only (`pg_regress.c:2893`).

`basic_diff_opts` decides pass/fail (`pg_regress.c:1912-1914`); `pretty_diff_opts`
produces what gets appended to `regression.diffs` (`:2017-2019`). Reproduce the
latter by hand:

```sh
cd src/test/regress
./gpdiff.pl -I HINT: -I CONTEXT: -I GP_IGNORE: -U3 \
    --gpd_init init_file \
    expected/<t>.out results/<t>.out
```

See the normalised form of one file alone (`atmsort.pl` reads stdin, writes
stdout, `atmsort.pl:373`):

```sh
./atmsort.pl --gpd_init init_file < results/<t>.out | less

# which mask fired on which line
./atmsort.pl --gpd_init init_file --verbose < results/<t>.out | grep GP_IGNORE:

# is this test's ORDER BY total, or does it leave ties unordered?
./atmsort.pl --gpd_init init_file --order_warn < results/<t>.out \
  | grep ORDER_WARNING
# GP_IGNORE: ORDER_WARNING: OUTPUT 4 columns, but ORDER BY on 1
```

`--order_warn` (`atmsort.pm:923-960`) compares the number of ORDER BY columns
against the number of output columns. A warning means the query's row order is
only partially determined — the answer file will flutter on ties.

## Where results and diffs land

| Command | results | diffs |
|---|---|---|
| `make -C src/test/regress installcheck-good` | `src/test/regress/results/<t>.out` | `src/test/regress/regression.diffs` |
| `make -C src/test/regress installcheck-tests TESTS="a b"` | same | same |
| `make -C src/test/isolation2 installcheck` | `src/test/isolation2/results/` | `src/test/isolation2/regression.diffs` |
| `installcheck-resgroup`, `-resgroup-v2` | `src/test/isolation2/resgroup/results/` | `src/test/isolation2/resgroup/regression.diffs` |
| `installcheck-parallel-retrieve-cursor` | `…/parallelretrcursor/results/` | `…/parallelretrcursor/regression.diffs` |
| `installcheck-mirrorless` (isolation2) | `…/mirrorless/results/` | `…/mirrorless/regression.diffs` |
| `installcheck-hot-standby` | `…/hot_standby/results/` | `…/hot_standby/regression.diffs` |
| `installcheck-ic-tcp` / `installcheck-ic-proxy` | `…/ic_tcp/results/`, `…/ic_proxy/results/` | matching `regression.diffs` |
| `installcheck-resource-queue` | `…/resqueue/results/` | `…/resqueue/regression.diffs` |
| any `gpcontrib/`, `contrib/`, `src/pl/` module | that module's own `results/` | that module's own `regression.diffs` |

`installcheck-world` runs many of these, so **always `find . -name regression.diffs`**
rather than assuming one file. That is exactly what the containerised runner does
on failure: `concourse/scripts/ic_gpdb.bash:14` collects
`` diff_files=`find .. -name regression.diffs` `` and cats every one into the log.

`regression.diffs` and `regression.out` are deliberately **not** in
`src/test/regress/.gitignore` — the comment there says they are only left behind
on failure. `results/`, `log/` and `tmp_check/` are ignored.

pg_regress deletes `regression.diffs` and `regression.out` when the run has no
failures (`pg_regress.c:3458`). A stale `regression.diffs` means a stale run.

## Databases pg_regress creates

Unless `--use-existing` is passed, pg_regress **drops and recreates** each
database in its `--dbname` list before the run (`pg_regress.c:3327-3350`,
`create_database` uses `TEMPLATE=template0`). Defaults: `regression` for the
regress suite (`pg_regress_main.c:173`) and `isolation2test` for isolation2
(`isolation2_main.c:146`); isolation2 targets override it — `isolation2resgrouptest`,
`isolation2parallelretrcursor`, `isolation2resourcequeue`,
`isolation2-mirrorless`, `isolation2-hot-standby`; regress overrides it for
`installcheck-icudp` (`regression_icudp`) and `installcheck-mirrorless`
(`regress-mirrorless`).

Consequence: a single-test run starts from an empty database. `parallel_schedule`
and `greengage_schedule` both open with `test: test_setup` under a "required setup
steps" comment (7.x only — 6.x has no `sql/test_setup.sql`), and `tenk1` / `onek`
are created by `sql/create_table.sql`, not by `test_setup`. Running
`installcheck-tests TESTS="select"` alone therefore fails with
`ERROR:  relation "onek" does not exist` (`sql/select.sql` reads `onek`; tests that
read `tenk1` fail the same way) — a setup failure, not a regression.

## `.source`-generated tests

`convert_sourcefiles()` (`pg_regress.c:963`) runs at startup:

| Source | Generated into | Suffix |
|---|---|---|
| `input/<t>.source` | `$outputdir/sql/<t>.sql` | `sql` |
| `output/<t>.source` | `$outputdir/expected/<t>.out` | `out` |
| `yml_in/<t>.source` | `$inputdir/yml/<t>.yml` | `yml` — code path only, no `yml_in/` directory ships on 7.x |
| `input/hooks/<t>.source` | `$outputdir/sql/hooks/<t>.sql` | `sql` — only when `--prehook=NAME` is passed (`pg_regress.c:3069-3075`); no `input/hooks/` directory ships on 7.x |

With the default `--inputdir=. --outputdir=.` the generated files land **in the
tracked `sql/` and `expected/` directories**, which is why 58 entries in
`src/test/regress/sql/.gitignore` and 63 in
`src/test/regress/expected/.gitignore` exist. 7.x has 80 `.source` files under
`input/` and 90 under `output/` — 50 and 58 at the top level, the rest in
`uao_ddl/` and `uao_dml/`.

Tokens substituted (`convert_line`, `pg_regress.c:586`):

`@cgroup_mnt_point@` `@abs_srcdir@` `@abs_builddir@` `@testtablespace@`
`@libdir@` `@DLSUFFIX@` `@bindir@` `@hostname@` (hostname of content 0 primary)
`@curusername@` `@amname@` `@aoseg@`

plus `@gpwhich_<executable>@`, handled separately by `gpstringsubs.pl`.

### UAO row/column generation

A directory under `input/`/`output/` containing a file literally named
`GENERATE_ROW_AND_COLUMN_FILES` makes pg_regress emit **two** tests per `.source`
(`generate_uao_sourcefiles`, `pg_regress.c:612`). Four such directories ship on
7.x: `input/uao_ddl/`, `input/uao_dml/` and their `output/` twins (22 and 8
`.source` files under `input/`, 23 and 9 under `output/`). The `src/test/regress/README`
calls the convention `input/uao*/`, so a new one only has to match that shape:

| `.source` | generates |
|---|---|
| `input/uao_ddl/<t>.source` | `sql/uao_ddl/<t>_row.sql`, `sql/uao_ddl/<t>_column.sql` |
| `output/uao_ddl/<t>.source` | `expected/uao_ddl/<t>_row.out`, `<t>_column.out` |
| `output/uao_ddl/<t>_optimizer.source` | `expected/uao_ddl/<t>_row_optimizer.out`, `<t>_column_optimizer.out` |

`expected/uao_ddl/` and `expected/uao_dml/` contain only a `.gitignore` (`*.out`)
and a README saying "This directory only contains generated files." Every `.source`
in an `input/uao*/` or `output/uao*/` directory must begin
with the three-line header documented in `src/test/regress/README`:

```sql
create schema <filename_prefix>@amname@;
set search_path="$user",<filename_prefix>@amname@,public;
SET default_table_access_method=@amname@;
```

## Make targets for a targeted rerun

| Target | Runs |
|---|---|
| `make -C src/test/regress installcheck-tests TESTS="test_setup create_table select"` | just those, in that order, against a freshly created `regression` db |
| `make -C src/test/regress installcheck-good` | `parallel_schedule` then `greengage_schedule` — the real suite |
| `make -C src/test/regress installcheck-small` | `parallel_schedule` only |
| `make -C src/test/isolation2 installcheck` | resource-queue + parallel-retrieve-cursor + ic-tcp + ic-proxy + `isolation2_schedule` |

`make check` and plain `make installcheck` at the top level do not work on
Greengage — see [greengage-testing](../../greengage-testing/SKILL.md).

## pg_regress status strings you will see

| String | Meaning | Source |
|---|---|---|
| `ok    ` | gpdiff found no difference | `pg_regress.c:2383` |
| `FAILED` | gpdiff found a difference | `pg_regress.c:2377` |
| `failed (ignored)` | ditto, but the schedule carries `ignore: <test>` | `pg_regress.c:2372` |
| `The differences that caused some tests to fail can be viewed in the` | end-of-run pointer at `regression.diffs` | `pg_regress.c:3451` |
