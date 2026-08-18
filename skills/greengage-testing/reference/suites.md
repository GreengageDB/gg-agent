# Greengage test-suite inventory

Every suite, the exact command, what it covers, and its top gotcha. Re-derived from
`refs/remotes/origin/7.x` of `GreengageDB/greengage`: `GNUmakefile.in`,
`src/test/regress/GNUmakefile`, `src/test/isolation2/Makefile`, `src/test/Makefile`,
`gpMgmt/Makefile.behave`, `ci/readme.md`. 6.x deltas noted per row.

All commands assume the environment is already correct:

```sh
source /usr/local/gpdb/greengage_path.sh  # 7.x README prefix; CI container: /usr/local/greengage-db-devel
                                          # this script is what SETS $GPHOME - do not use $GPHOME to find it
source gpAux/gpdemo/gpdemo-env.sh
export LANG=en_US.UTF-8
```

`7.x only` marks a target that does not exist on `refs/remotes/origin/6.x`.

## Summary table

| Suite | Command (from repo root unless noted) | Covers | Top gotcha |
|---|---|---|---|
| Everything | `make -k installcheck-world` | `ICW_TARGETS` + `src/test/ssl check` + `gpcheckcat -A` + `vacuumdb --all --analyze-only --jobs=5` (7.x only — 6.x has no `installcheck-analyze`) + `gpcontrib/gp_replica_check` + `src/bin/pg_upgrade check` (6.x: `contrib/pg_upgrade`) | Multi-hour. The `pg_upgrade` leg stops and restarts the demo cluster (`src/bin/pg_upgrade/test_gpdb.sh:420,445`); `gpcheckcat -A` fails on any leftover inconsistent database from an earlier aborted suite |
| Core regress, both schedules | `make -C src/test/regress installcheck-good` (= `installcheck`) | `parallel_schedule` **then** `greengage_schedule` into one `regression` db; 665 distinct tests (197 + 471, 3 shared) | Two schedules, one database. `installcheck-good` passes **no** `--max-connections`; cap concurrency with `EXTRA_REGRESS_OPTS='--max-connections=N'` |
| Core regress, upstream only | `make -C src/test/regress installcheck-small` | `parallel_schedule` only (197 tests) | Pollution-free upstream baseline, but leaves `regression` half-populated for a later `installcheck-good` — that target drops the db first, so this is safe |
| Core regress, concurrency-capped | `make -C src/test/regress installcheck-parallel MAX_CONNECTIONS=4` | `parallel_schedule` with `--max-connections` | Only `installcheck-parallel`, `check`, `check-tests` and `bigcheck` expand `$(MAXCONNOPT)`; every other target ignores `MAX_CONNECTIONS` |
| Named tests | `make -C src/test/regress installcheck-tests TESTS="qp_misc gp_dqa"` | Just those tests, in order | **Drops and recreates `regression`** — no `--use-existing`. Tests with setup dependencies fail with missing `tenk1`/`onek`/`point_tbl` |
| Extra tests after a schedule | `make -C src/test/regress installcheck-good EXTRA_TESTS="mytest"` | Schedule, then the extras, sequentially | The extras see the fully-populated post-schedule database |
| Interconnect UDP | `make -C src/test/regress installcheck-icudp` | `icudp_schedule`, db `regression_icudp`: `test_setup`, then a 15-test interconnect group, then the slow `icudp/icudp_full` | Prints `icudp tests can not run in production builds, skipped` and exits 0 when `BUILD_TYPE=prod`. `icudp/disorder_fuc` is `ignore:`-listed and must stay that way |
| Mirrorless regress | `make installcheck-mirrorless` (top level) | `src/test/regress mirrorless_schedule` (db `regress-mirrorless`) + `src/test/isolation2 mirrorless_schedule` (db `isolation2-mirrorless`) | Needs a cluster built `WITH_MIRRORS=false`; the isolation2 half is crash-recovery/FTS and will not pass on a mirrored cluster |
| Hot standby regress | `make -C src/test/regress standbycheck` | `standby_schedule` — run **against the standby** | Requires `psql -f src/test/regress/sql/hs_primary_setup.sql regression` on the primary first (documented in the schedule header) |
| Upstream isolation | `make -C src/test/isolation installcheck` | `isolation_schedule` specs, db `isolation_regression`, `--load-extension=pageinspect` | The `dropdb --if-exists isolation_regression` is a **separate make line after** the test line: a failed run leaves the db behind, and it is QD/segment-inconsistent by design, so the next `gpcheckcat -A` fails |
| isolation2, main | `make -C src/test/isolation2 installcheck` | `isolation2_schedule` (272 test lines), db `isolation2test`; also chains `installcheck-resource-queue`, `-parallel-retrieve-cursor`, `-ic-tcp`, `-ic-proxy` | Runs the **installed** `pg_isolation2_regress` from `$(pg_config --pkglibdir)/pgxs/src/test/isolation2/`; `make install` after any harness edit or you test a stale binary |
| isolation2, resource queue (7.x only) | `make -C src/test/isolation2 installcheck-resource-queue` | 10 specs, db `isolation2resourcequeue`, outputdir `resqueue` | First spec is `resource_manager_switch_to_queue` and the last is `resource_manager_restore_to_none` — they `gpconfig`+restart the cluster. Aborting mid-schedule leaves `gp_resource_manager` changed |
| isolation2, resgroup v1 | `make -C src/test/isolation2 installcheck-resgroup` | `isolation2_resgroup_v1_schedule` (28), db `isolation2resgrouptest`, outputdir `resgroup`, `init_file_resgroup` | First spec `resgroup/resgroup_auxiliary_tools_v1` runs `gpconfig -c gp_resource_manager -v group`, `max_connections 250/25`, `gpstop -rai`. Needs cgroup **v1** dirs `/sys/fs/cgroup/{cpu,cpuacct,cpuset}/gpdb` and `plpython3u` |
| isolation2, resgroup v2 (7.x only) | `make -C src/test/isolation2 installcheck-resgroup-v2` | `isolation2_resgroup_v2_schedule` (30) — same specs plus `resgroup_io_limit*` | First spec sets `gp_resource_manager=group-v2` and `gp_resource_group_cgroup_parent=gpdb`; needs cgroup **v2** at `/sys/fs/cgroup/gpdb/*`. Same db and outputdir as v1, so a v1 run's artifacts are overwritten |
| isolation2, hot standby (7.x only) | `make -C src/test/isolation2 installcheck-hot-standby` | 4 specs `hot_standby/{setup,basic,faults,teardown}`, db `isolation2-hot-standby` | The schedule is setup/teardown-bracketed: running one spec alone leaves the standby reconfigured |
| isolation2, retrieve cursors | `make -C src/test/isolation2 installcheck-parallel-retrieve-cursor` | 16 specs, db `isolation2parallelretrcursor`, `init_file_parallel_retrieve_cursor` | Needs the built helpers `test_parallel_retrieve_cursor_extended_query{,_error}`; retrieve-mode sessions use the `R` session flag and token plumbing from `global_sh_executor.sh` |
| isolation2, ic-tcp | `make -C src/test/isolation2 installcheck-ic-tcp PGOPTIONS='-c gp_interconnect_type=tcp'` | 1 spec, `tcp_ic_teardown` | The recipe is inside `ifeq ($(findstring gp_interconnect_type=tcp,$(PGOPTIONS))…)`. Without the matching `PGOPTIONS` it is a **silent no-op that exits 0** |
| isolation2, ic-proxy | `make -C src/test/isolation2 installcheck-ic-proxy PGOPTIONS='-c gp_interconnect_type=proxy'` | 3 specs incl. `ic_proxy_peer_shutdown`, `ic_proxy_listen_failed` | Same silent-no-op guard; also needs a `--enable-ic-proxy` build and per-segment `gp_interconnect_proxy_addresses` (see `concourse/scripts/common.bash` `make_cluster`) |
| gpcontrib extensions | `make -C gpcontrib installcheck` | 7.x: `gp_internal_tools`, `orafce`, `zstd`, `gp_sparse_vector`, `gp_exttable_fdw`, `gp_toolkit`, `gg_tables_tracking` (+ its isolation2), `gg_wait_sampling` (+ its isolation2) | `gg_tables_tracking` and `gg_wait_sampling` are Greengage-original and have no upstream counterpart; each sub-suite has its own db. **6.x's list is completely different** — `gp_array_agg`, `gpmapreduce`, `quicklz`, `gp_percentile_agg`, `gp_subtransaction_overflow`, `gp_check_functions`, `temp_tables_stat`, `credcheck`, and no `gg_*` |
| gpcontrib resgroup | `make -C gpcontrib installcheck-resgroup` | `gg_wait_sampling/isolation2` under resource groups | Only reached via the top-level `installcheck-resgroup`, which recurses into both `src/test/isolation2` and `gpcontrib` |
| contrib extensions | `make -C contrib/<name> install && make -C contrib/<name> installcheck` | `ICW_TARGETS` list (see below) | All PGXS `installcheck` runs share the db `contrib_regression`; a hung session from one extension makes every later `DROP DATABASE` fail |
| mock unit tests | `make -s unittest-check` | cmockery mocks under `src/backend/**/test/` and `src/bin/pg_dump/test` | Needs no cluster. Recurses serially; a failure aborts the recursion, so the first red binary hides the rest |
| gpMgmt python units | `make -C gpMgmt/bin unitdevel` | `gppylib` `test_unit*.py` via `python3 -m unittest discover` | `make -C gpMgmt/bin check` is a different target that also runs `test_cluster*.py` and needs a live cluster; instead of printing, it redirects stderr to `gpMgmt_testunit_results.log` and stdout to `gpMgmt_testunit_output.log` |
| gpMgmt bash | `make -C gpMgmt/bin installcheck` | `test/suite.bash` → `test/gpinitsystem_test.bash` (two `SET_GP_USER_PW` cases that `createuser`/`dropuser` roles `123456` and `abc123456` on the running cluster), then `gpload_test` | It does **not** build a cluster, but it does create roles in yours. `gpload_test/Makefile` prints `skip gpload test for ubuntu` and does nothing when `TEST_OS` contains `ubuntu` — a green line there means the gpload tests never ran |
| behave (mgmt utils) | `IMAGE=greengage7_u22:$BRANCH_NAME bash ci/scripts/run_behave_tests.bash [gpstart gpstop …]` | 23 `.feature` files in `gpMgmt/test/behave/mgmt_utils/` | docker-compose, 4 hosts `cdw`/`sdw1..3`, 3 features in parallel. With no arguments it skips `cross_subnet`, `gpssh` and `gpexpand` |
| behave (single feature, local) | `cd gpMgmt && make -f Makefile.behave behave tags=gpstart` | One tag's scenarios against the local demo cluster | Set `PYTHONPATH` to include `gpMgmt/test`; CI selects `--tags <feature> --tags=~concourse_cluster`, and a scenario tagged **both** `@concourse_cluster` and `@demo_cluster` is still excluded |
| resgroup, container flavor | `IMAGE=<image> LOGS=$PWD/logs OPTIMIZER=off bash ci/scripts/run_resgroup_test.bash` | `make PGOPTIONS='-c optimizer=off -c statement_mem=125MB' installcheck-resgroup` inside a `--privileged` container | The script `chmod -R 777 /sys/fs/cgroup/{memory,cpu,cpuset}` and creates `…/gpdb` — that setup is why resgroup tests do not work in an unprivileged container |
| JIT (7.x only) | see `ci/readme.md`; `MAKE_TEST_COMMAND="-k PGOPTIONS='-c optimizer=on -c jit=on -c jit_above_cost=0 -c optimizer_jit_above_cost=0 -c gp_explain_jit=off' installcheck"` | The same regress tests with JIT forced on; no separate schedule or answer files | Needs a `--with-llvm` build (`configure.in:426`, default **no**). Without `llvmjit.so` the provider load is skipped silently (`src/backend/jit/jit.c:93-95`) and the run proves nothing — check `SELECT pg_jit_available();` |
| ORCA unit tests | `cd src/backend/gporca && cmake -GNinja -H. -Bbuild && ninja -C build && (cd build && ctest -j8 --output-on-failure)` | GPORCA C++ unit tests and minidumps | Needs CMake ≥ 3.1 and Ninja. Some assertions only exist in DEBUG builds, so a Release ctest is weaker |
| ORCA, one test / minidump | `./server/gporca_test -U CAggTest` or `./server/gporca_test -d ../data/dxl/minidump/TVFRandom.mdp` (from `build/`) | A single suite or minidump | Regenerate failing minidumps with `ctest -j8 --rerun-failed --output-on-failure \| tee /tmp/failures.out` then `src/backend/gporca/scripts/fix_mdps.py --logFile /tmp/failures.out` (use `--dryRun` first) |
| ORCA in a container | `docker run --rm -it gpdb7_u22:latest bash -c "gpdb_src/concourse/scripts/unit_tests_gporca.bash"` | RelWithDebInfo **and** Debug ctest passes | CPU-heavy: two full cmake builds |
| ORCA formatting | `docker build -t orca-linter:test -f ci/Dockerfile.linter . && docker run --rm -it orca-linter:test` | clang-format check of ORCA sources | Requires a clean work tree (`ci/readme.md`). Locally: `CLANG_FORMAT=clang-format src/tools/fmt chk`, `CLANG_TIDY=clang-tidy-12 src/tools/tidy build.debug` |
| pg_upgrade | `make -C src/bin/pg_upgrade check` | `bash test_gpdb.sh -C -r -s -O $(top_builddir)/gpAux/gpdemo/datadirs/ -b $(DESTDIR)$(bindir)` | There is no `installcheck` — the Makefile says "no meaningful way to test pg_upgrade against a single already-running server". It gpstops the demo cluster |
| TAP suites | inside `installcheck-world` via `src/test/{recovery,authentication,ssl,kerberos,ldap}` | perl `prove` tests | Without `--enable-tap-tests` these print `TAP tests not enabled` and pass vacuously. `ssl`/`kerberos`/`ldap` additionally need `PG_TEST_EXTRA` to name them (CI uses `PG_TEST_EXTRA="kerberos ssl"`) |
| Full container run | `docker run --name gpdb7_opt_on --rm -it -e TEST_OS=ubuntu -e MAKE_TEST_COMMAND="-k PGOPTIONS='-c optimizer=on' installcheck-world" --sysctl "kernel.sem=500 1024000 200 4096" gpdb7_u22:latest /home/gpadmin/gpdb_src/concourse/scripts/ic_gpdb.bash` | Build image, demo cluster, then the named make target | `ic_gpdb.bash` traps ERR and prints every `regression.diffs` it can find — read that, not the make tail. `--sysctl kernel.sem=…` is mandatory or the cluster will not start |

## `ICW_TARGETS` (7.x, `GNUmakefile.in`)

```
src/test  src/pl  src/interfaces/gppc
contrib/auto_explain  contrib/citext  contrib/btree_gin  contrib/pg_stat_statements
contrib/file_fdw  contrib/postgres_fdw  contrib/formatter_fixedwidth
contrib/extprotocol  contrib/dblink  contrib/pg_trgm
contrib/indexscan  contrib/hstore  contrib/ltree  contrib/pgcrypto  contrib/isn
contrib/pg_buffercache
contrib/sslinfo        # only if with_openssl=yes
contrib/tablefunc
contrib/uuid-ossp      # only if with_uuid != no
gpcontrib  src/bin  gpMgmt/bin
```

`src/test` itself recurses into `perl regress isolation modules authentication recovery
fsync walrep heap_checksum isolation2 fdw` (`installcheck` skips `modules`).

**6.x differences:** `ICW_TARGETS` has `contrib/amcheck` and no `contrib/file_fdw`;
`contrib/dblink` and `contrib/postgres_fdw` are excluded on Darwin. `src/test` SUBDIRS
adds `ssl kerberos modules` unconditionally instead of gating them on `PG_TEST_EXTRA`.

## Regression schedules (`src/test/regress/`)

| Schedule | Used by | Test lines |
|---|---|---|
| `parallel_schedule` | `installcheck-small`, `installcheck-parallel`, `installcheck-good`, `check`, `bigcheck` | 33 groups / 197 distinct |
| `greengage_schedule` | `installcheck-good` (second schedule) | 180 groups / 471 distinct |
| `serial_schedule` | `bigtest` only | 192 |
| `icudp_schedule` | `installcheck-icudp` | 3 |
| `mirrorless_schedule` | `installcheck-mirrorless` | 9 |
| `standby_schedule` | `standbycheck` | 5 |
| `minimal_schedule` | nothing on 7.x (6.x `testbouncer`) | 2 |

On 7.x only three names appear in both `parallel_schedule` and `greengage_schedule`:
`test_setup`, `disable_autovacuum`, `enable_autovacuum`. All three are written to be
re-runnable, which is why running the two schedules into one database is safe.
`installcheck-good` therefore runs 665 distinct tests (197 + 471 − 3).

**6.x:** 145 + 416 distinct, and **no name appears in both** — 6.x's `greengage_schedule`
carries none of `test_setup`, `disable_autovacuum`, `enable_autovacuum`.

## isolation2 schedules (`src/test/isolation2/`)

| Schedule | Target | Database | Output dir | Test lines |
|---|---|---|---|---|
| `isolation2_schedule` | `installcheck` | `isolation2test` | `.` | 272 |
| `isolation2_resqueue_schedule` | `installcheck-resource-queue` (7.x) | `isolation2resourcequeue` | `resqueue` | 10 |
| `isolation2_resgroup_v1_schedule` | `installcheck-resgroup` | `isolation2resgrouptest` | `resgroup` | 28 |
| `isolation2_resgroup_v2_schedule` | `installcheck-resgroup-v2` (7.x) | `isolation2resgrouptest` | `resgroup` | 30 |
| `parallel_retrieve_cursor_schedule` | `installcheck-parallel-retrieve-cursor` | `isolation2parallelretrcursor` | `parallelretrcursor` | 16 |
| `mirrorless_schedule` | `installcheck-mirrorless` | `isolation2-mirrorless` | `mirrorless` | 9 |
| `hot_standby_schedule` | `installcheck-hot-standby` (7.x) | `isolation2-hot-standby` | `hot_standby` | 4 |
| `isolation2_ic_tcp_schedule` | `installcheck-ic-tcp` | `isolation2test` | `ic_tcp` | 1 |
| `isolation2_ic_proxy_schedule` | `installcheck-ic-proxy` | `isolation2test` | `ic_proxy` | 3 |

**6.x:** the resgroup schedule is `isolation2_resgroup_schedule` (no v1/v2 split); there
is no `isolation2_resqueue_schedule` and no `hot_standby_schedule`.

## Harness tooling next to the tests

| File | Role |
|---|---|
| `src/test/regress/pg_regress.c` | driver: db create/drop, `--use-existing`, expected-file selection, diff invocation, tally |
| `src/test/regress/gpdiff.pl` | wraps `diff` with atmsort preprocessing; diff flags `-I HINT: -I CONTEXT: -I GP_IGNORE:` |
| `src/test/regress/atmsort.pl`, `atmsort.pm` | sorts unordered SELECT output, reformats EXPLAIN, applies `matchignore`/`matchsubs` |
| `src/test/regress/explain.pl`, `explain.pm` | reduces an EXPLAIN plan to a nested id/parent/short structure |
| `src/test/regress/gpstringsubs.pl` | in-place substitution of `@gpwhich_<exe>@` (full path of an executable) and `@gp_syslocale@` (the cluster's `LC_CTYPE`) — *not* hostnames or ports |
| `src/test/regress/init_file` | global `matchignore` / `matchsubs` applied to every regress and isolation2 run |
| `src/test/isolation2/init_file_isolation2` | isolation2-specific masks |
| `src/test/isolation2/init_file_resgroup` | resgroup-specific masks |
| `src/test/isolation2/init_file_parallel_retrieve_cursor` | retrieve-cursor masks |
| `src/test/isolation2/sql_isolation_testcase.py` | **the isolation2 spec syntax reference** — session prefixes, flags, `@db_name`, `@pre_run`/`@post_run` |
| `src/test/isolation2/global_sh_executor.sh` | shell helpers sourced for `@pre_run`/`@post_run` |
| `src/test/regress/scan_flaky_fault_injectors.sh` | pre-run guard: fails if a fault-injection test sits in a parallel group |

## Environment and output artefacts

| Artefact | Where |
|---|---|
| `regression.diffs` | `$outputdir/regression.diffs`; truncated at run start, **unlinked on a clean run** |
| `regression.out` | `$outputdir/regression.out`; same lifecycle |
| per-test results | `$outputdir/results/<test>.out` |
| isolation2 sub-suite artefacts | `src/test/isolation2/<outputdir>/` per the table above |
| behave allure output | `allure-results/` (created by `ci/scripts/run_behave_tests.bash`) |

`src/test/regress/.gitignore` documents the lifecycle explicitly: *"regreesion.\* are only
left behind on a failure; that's why they're not ignored"*.
